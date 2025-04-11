#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
compile_with_retry.py
用于修复 OpenWrt 编译中的常见错误，包括下载失败
用法: python3 compile_with_retry.py <make_command> <log_file> [--max-retry N] [--error-pattern PATTERN]
"""

import argparse
import os
import re
import subprocess
import sys
import time
import shutil
import requests
import hashlib
import tempfile
from pathlib import Path

def get_latest_github_release(repo):
    """从 GitHub API 获取最新版本"""
    api_url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        response = requests.get(api_url)
        if response.status_code == 200:
            return response.json().get('tag_name')
        else:
            print(f"从 GitHub API 获取版本信息失败, 状态码: {response.status_code}")
            # 如果 API 限制，可以尝试直接解析 HTML
            html_url = f"https://github.com/{repo}/releases"
            html_response = requests.get(html_url)
            if html_response.status_code == 200:
                # 简单解析，寻找版本标签
                release_match = re.search(r'href="/[^/]+/[^/]+/releases/tag/([^"]+)"', html_response.text)
                if release_match:
                    return release_match.group(1)
    except Exception as e:
        print(f"获取版本信息时出错: {e}")
    return None

def fix_lua_neturl():
    """修复 lua-neturl 包的下载问题"""
    print("尝试修复 lua-neturl 下载问题...")
    
    # 查找 Makefile 路径
    makefile_path = None
    for path in ["feeds/small8/lua-neturl/Makefile", "package/feeds/small8/lua-neturl/Makefile"]:
        if os.path.isfile(path):
            makefile_path = path
            break
    
    if not makefile_path:
        print("错误: 无法找到 lua-neturl 的 Makefile")
        return False
    
    print(f"找到 Makefile: {makefile_path}")
    
    # 读取当前 Makefile
    with open(makefile_path, 'r', errors='replace') as f:
        makefile_content = f.read()
    
    # 获取当前版本
    version_match = re.search(r'^PKG_VERSION:=(.*)$', makefile_content, re.MULTILINE)
    if not version_match:
        print("错误: 无法从 Makefile 中提取 PKG_VERSION")
        return False
    
    current_version = version_match.group(1).strip()
    print(f"当前版本: {current_version}")
    
    # 获取 PKG_SOURCE_URL 以提取 GitHub 仓库
    source_url_match = re.search(r'^PKG_SOURCE_URL:=(.*)$', makefile_content, re.MULTILINE)
    repo = "golgote/neturl"  # 默认仓库
    if source_url_match:
        url = source_url_match.group(1).strip()
        github_match = re.search(r'github\.com/([^/]+/[^/]+)', url)
        if github_match:
            repo = github_match.group(1)
            print(f"从 PKG_SOURCE_URL 提取的仓库: {repo}")
        else:
            print(f"使用默认仓库: {repo}")
    
    # 动态获取最新版本
    latest_tag = get_latest_github_release(repo)
    if not latest_tag:
        print("警告: 无法获取最新版本，尝试使用 v1.2-1")
        latest_tag = "v1.2-1"
    
    # 从标签中提取版本号 (去掉前缀 v)
    new_version = latest_tag.lstrip('v')
    print(f"获取到最新版本: {new_version}")
    
    if current_version == new_version:
        print(f"当前版本 {current_version} 已经是最新的，检查是否需要修复其他问题")
    
    # 获取新版本的 tarball
    download_url = f"https://github.com/{repo}/archive/refs/tags/{latest_tag}.tar.gz"
    print(f"尝试下载: {download_url}")
    
    try:
        response = requests.get(download_url, stream=True)
        if response.status_code != 200:
            print(f"下载失败，状态码: {response.status_code}")
            return False
        
        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            for chunk in response.iter_content(chunk_size=8192):
                tmp_file.write(chunk)
            tarball_path = tmp_file.name
    except Exception as e:
        print(f"下载文件时出错: {e}")
        return False
    
    # 计算新版本的哈希值
    with open(tarball_path, 'rb') as f:
        new_hash = hashlib.sha256(f.read()).hexdigest()
    print(f"新哈希值: {new_hash}")
    
    # 更新 Makefile
    new_content = re.sub(
        r'^PKG_VERSION:=.*$',
        f'PKG_VERSION:={new_version}',
        makefile_content,
        flags=re.MULTILINE
    )
    
    new_content = re.sub(
        r'^PKG_HASH:=.*$',
        f'PKG_HASH:={new_hash}',
        new_content,
        flags=re.MULTILINE
    )
    
    # 提取包名前缀
    pkg_name_match = re.search(r'^PKG_SOURCE:=(.*)-\$\(PKG_VERSION\)\.tar\.gz$', new_content, re.MULTILINE)
    pkg_name = "neturl"  # 默认包名
    if pkg_name_match:
        pkg_name = pkg_name_match.group(1)
    
    # 更新 PKG_SOURCE 和 PKG_SOURCE_URL 如果必要
    if re.search(r'^PKG_SOURCE:=', new_content, re.MULTILINE):
        new_content = re.sub(
            r'^PKG_SOURCE:=.*$',
            f'PKG_SOURCE:={pkg_name}-$(PKG_VERSION).tar.gz',
            new_content,
            flags=re.MULTILINE
        )
    
    # 修复GitHub URL末尾的问号（如果存在）
    if re.search(r'^PKG_SOURCE_URL:=.*github\.com.*\?$', new_content, re.MULTILINE):
        new_content = re.sub(
            r'^(PKG_SOURCE_URL:=.*github\.com.*)\?$',
            r'\1',
            new_content,
            flags=re.MULTILINE
        )
    
    # 保存修改
    with open(makefile_path, 'w') as f:
        f.write(new_content)
    
    # 清理
    os.remove(tarball_path)
    
    print(f"已更新 {makefile_path}，版本从 {current_version} 更新到 {new_version}")
    
    # 尝试清理包目录以便重新编译
    pkg_dir = os.path.dirname(makefile_path)
    print(f"尝试清理目录: {pkg_dir}...")
    try:
        subprocess.run(["make", f"{pkg_dir}/clean", "V=s"], check=False)
    except Exception as e:
        print(f"清理目录时出错: {e}")
    
    return True
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
    """修复 Makefile 'missing separator' 错误"""
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
    
    context_dir = None
    log_lines = log_content.splitlines()
    error_line_info = error_line_match.group(0)
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
                print(f"第 {line_num} 行无需修复或问题不在缩进。")
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
    
    return fix_attempted == 1


def fix_trojan_plus_boost_error():
    """修复 trojan-plus 中的 boost::asio::buffer_cast 错误"""
    print("修复 trojan-plus 中的 boost::asio::buffer_cast 错误...")
    found_path = ""
    trojan_pkg_dir = ""
    
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
                match = re.search(r'build_dir/[^/]*/([^/]*)/src/core', trojan_src_dir)
                if match:
                    trojan_pkg_dir = match.group(1)
                print(f"找到 trojan-plus 源码: {found_path} (包构建目录推测: {trojan_pkg_dir})")
    except subprocess.SubprocessError:
        print("在 build_dir 中搜索 trojan-plus 源码时出错")
    
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
    shutil.copy2(found_path, f"{found_path}.bak")
    with open(found_path, 'r', errors='replace') as f:
        content = f.read()
    modified_content = re.sub(
        r'boost::asio::buffer_cast<char\*>\((udp_read_buf\.prepare\([^)]*\))\)',
        r'static_cast<char*>(\1.data())',
        content
    )
    with open(found_path, 'w') as f:
        f.write(modified_content)
    with open(found_path, 'r') as f:
        if 'static_cast<char*>' in f.read():
            print(f"已成功修改 {found_path}")
            os.remove(f"{found_path}.bak")
            if trojan_pkg_dir:
                pkg_name = re.sub(r'-[0-9].*', '', trojan_pkg_dir)
                pkg_src_paths = subprocess.check_output(
                    ["find", "package", "feeds", "-name", pkg_name, "-type", "d", "-print", "-quit"],
                    text=True
                ).strip()
                if pkg_src_paths:
                    pkg_src_path = pkg_src_paths.split("\n")[0]
                    if os.path.isdir(pkg_src_path):
                        print(f"尝试清理包 {pkg_src_path} 以应用更改...")
                        try:
                            subprocess.run(["make", f"{pkg_src_path}/clean", "DIRCLEAN=1", "V=s"], check=False)
                        except:
                            print(f"警告: 清理包 {pkg_src_path} 失败。")
            return True
        else:
            print(f"尝试修改 {found_path} 失败，恢复备份文件。")
            shutil.move(f"{found_path}.bak", found_path)
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


def extract_github_repo(url):
    """从 URL 中提取 GitHub 仓库名"""
    match = re.search(r'github\.com/([^/]+)/([^/]+)', url)
    if match:
        return f"{match.group(1)}/{match.group(2)}"
    return None


def get_latest_version(repo):
    """从 GitHub API 获取最新版本"""
    api_url = f"https://api.github.com/repos/{repo}/releases/latest"
    response = requests.get(api_url)
    if response.status_code == 200:
        return response.json().get('tag_name')
    return None


def fix_download_failure(log_file):
    """修复下载失败错误"""
    print("检测到下载失败，尝试自动修复...")
    
    with open(log_file, 'r', errors='replace') as f:
        log_content = f.read()
    
    failed_pkg_match = re.search(r'download.pl ".*" "(\w+)-([\w.-]+)\.tar\.gz"', log_content)
    if not failed_pkg_match:
        print("无法从日志中提取失败的包名和版本。")
        return False
    
    failed_pkg = failed_pkg_match.group(1)
    failed_version = failed_pkg_match.group(2)
    print(f"失败的包: {failed_pkg}, 版本: {failed_version}")
    
    makefile_path = None
    for root, dirs, files in os.walk('feeds'):
        if failed_pkg in dirs:
            makefile_path = os.path.join(root, failed_pkg, 'Makefile')
            break
    
    if not makefile_path or not os.path.isfile(makefile_path):
        print(f"无法找到包 {failed_pkg} 的 Makefile。")
        return False
    
    print(f"找到 Makefile: {makefile_path}")
    
    with open(makefile_path, 'r', errors='replace') as f:
        makefile_content = f.read()
    
    source_url_match = re.search(r'^PKG_SOURCE_URL:=(.*)$', makefile_content, re.MULTILINE)
    if not source_url_match:
        print("无法从 Makefile 中提取 PKG_SOURCE_URL。")
        return False
    
    source_url = source_url_match.group(1).strip()
    print(f"PKG_SOURCE_URL: {source_url}")
    
    repo = extract_github_repo(source_url)
    if not repo:
        print("无法从 PKG_SOURCE_URL 中提取 GitHub 仓库名。")
        return False
    
    print(f"GitHub 仓库: {repo}")
    
    latest_version = get_latest_version(repo)
    if not latest_version:
        print("无法获取最新版本号。")
        return False
    
    print(f"最新版本号: {latest_version}")
    
    download_url = f"https://github.com/{repo}/archive/refs/tags/{latest_version}.tar.gz"
    print(f"下载 URL: {download_url}")
    
    try:
        response = requests.get(download_url, stream=True)
        if response.status_code != 200:
            print("下载 tarball 失败。")
            return False
        
        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            for chunk in response.iter_content(chunk_size=8192):
                tmp_file.write(chunk)
            tarball_path = tmp_file.name
    except Exception as e:
        print(f"下载 tarball 时出错: {e}")
        return False
    
    with open(tarball_path, 'rb') as f:
        new_hash = hashlib.sha256(f.read()).hexdigest()
    print(f"新哈希值: {new_hash}")
    
    new_content = re.sub(
        r'^PKG_VERSION:=.*$',
        f'PKG_VERSION:={latest_version}',
        makefile_content,
        flags=re.MULTILINE
    )
    
    if re.search(r'^PKG_HASH:=', new_content, re.MULTILINE):
        new_content = re.sub(
            r'^PKG_HASH:=.*$',
            f'PKG_HASH:={new_hash}',
            new_content,
            flags=re.MULTILINE
        )
    else:
        version_line = re.search(r'^PKG_VERSION:=.*$', new_content, re.MULTILINE)
        if version_line:
            insert_pos = version_line.end()
            new_content = new_content[:insert_pos] + f'\nPKG_HASH:={new_hash}' + new_content[insert_pos:]
        else:
            new_content += f'\nPKG_HASH:={new_hash}'
    
    with open(makefile_path, 'w') as f:
        f.write(new_content)
    
    os.remove(tarball_path)
    
    print("自动修复完成，PKG_VERSION 和 PKG_HASH 已更新。")
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
        
        current_version_match = re.search(r'^PKG_VERSION:=.*$', original_content, re.MULTILINE)
        release_match = re.search(r'^PKG_RELEASE:=.*$', original_content, re.MULTILINE)
        
        current_version = current_version_match.group(0) if current_version_match else ""
        release = release_match.group(0) if release_match else ""
        
        modified_in_loop = 0
        makefile_changed = 0
        
        version_suffix_match = re.match(r'^PKG_VERSION:=([0-9]+(\.[0-9]+)*)-([a-zA-Z0-9_.-]+)$', current_version)
        if version_suffix_match:
            new_version = version_suffix_match.group(1)
            suffix = version_suffix_match.group(3)
            suffix_num_match = re.search(r'[0-9]*$', re.sub(r'[^0-9]', '', suffix))
            new_release = suffix_num_match.group(0) if suffix_num_match and suffix_num_match.group(0) else "1"
            
            if not new_release.isdigit():
                new_release = "1"
            
            if current_version != f"PKG_VERSION:={new_version}" or release != f"PKG_RELEASE:={new_release}":
                print(f"修改 {makefile}: {current_version} -> PKG_VERSION:={new_version}, {release} -> PKG_RELEASE:={new_release}")
                new_content = re.sub(
                    r'^PKG_VERSION:=.*$',
                    f'PKG_VERSION:={new_version}',
                    original_content,
                    flags=re.MULTILINE
                )
                if re.search(r'^PKG_RELEASE:=', new_content, re.MULTILINE):
                    new_content = re.sub(
                        r'^PKG_RELEASE:=.*$',
                        f'PKG_RELEASE:={new_release}',
                        new_content,
                        flags=re.MULTILINE
                    )
                else:
                    version_line = re.search(r'^PKG_VERSION:=.*$', new_content, re.MULTILINE)
                    if version_line:
                        insert_pos = version_line.end()
                        new_content = new_content[:insert_pos] + f'\nPKG_RELEASE:={new_release}' + new_content[insert_pos:]
                    else:
                        new_content += f'\nPKG_RELEASE:={new_release}'
                
                with open(makefile, 'w') as f:
                    f.write(new_content)
                makefile_changed = 1
        
        elif release and not re.match(r'^PKG_RELEASE:=[0-9]+$', release):
            suffix_num_match = re.search(r'[0-9]*$', re.sub(r'[^0-9]', '', release))
            new_release = suffix_num_match.group(0) if suffix_num_match and suffix_num_match.group(0) else "1"
            if not new_release.isdigit():
                new_release = "1"
            if release != f"PKG_RELEASE:={new_release}":
                print(f"修正 {makefile}: {release} -> PKG_RELEASE:={new_release}")
                new_content = re.sub(
                    r'^PKG_RELEASE:=.*$',
                    f'PKG_RELEASE:={new_release}',
                    original_content,
                    flags=re.MULTILINE
                )
                with open(makefile, 'w') as f:
                    f.write(new_content)
                makefile_changed = 1
        
        elif not release and current_version and not re.search(r'^PKG_RELEASE:=', original_content, re.MULTILINE):
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


def main():
    parser = argparse.ArgumentParser(description='OpenWrt 编译修复脚本')
    parser.add_argument('make_command', help='编译命令，例如 "make -j1 V=s"')
    parser.add_argument('log_file', help='日志文件路径，例如 "compile.log"')
    parser.add_argument('--max-retry', type=int, default=8, help='最大重试次数 (默认: 8)')
    parser.add_argument('--error-pattern', 
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
    
    while retry_count <= args.max_retry:
        if retry_count > 1:
            print("--------------------------------------------------")
            print(f"尝试编译: {args.make_command} (第 {retry_count} / {args.max_retry} 次)...")
            print("--------------------------------------------------")
        
        fix_applied_this_iteration = 0
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
            print(f"编译失败 (退出码: {compile_status} 或在日志中检测到错误)，检查错误...")
            extract_error_block(log_tmp)
        
        # --- 错误检测和修复逻辑 ---
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
                
        # 新增：检测 lua-neturl 下载失败
        elif "Download failed" in log_content and "neturl" in log_content:
            print("检测到 lua-neturl 下载失败错误...")
            if last_fix_applied == "fix_lua_neturl":
                print("上次已尝试修复 lua-neturl 下载，但错误依旧，停止重试。")
                with open(args.log_file, 'a') as main_log:
                    with open(log_tmp, 'r', errors='replace') as tmp_log:
                        main_log.write(tmp_log.read())
                os.remove(log_tmp)
                return 1
            last_fix_applied = "fix_lua_neturl"
            if fix_lua_neturl():  # 调用新增的函数
                fix_applied_this_iteration = 1
                print("修复已应用，准备下一次编译尝试。")
            else:
                print("修复 lua-neturl 下载失败错误失败，停止重试。")
                with open(args.log_file, 'a') as main_log:
                    with open(log_tmp, 'r', errors='replace') as tmp_log:
                        main_log.write(tmp_log.read())
                os.remove(log_tmp)
                return 1
        
        elif "Download failed." in log_content:
            print("检测到下载失败错误...")
            if last_fix_applied == "fix_download_failure":
                print("上次已尝试修复下载失败，但错误依旧，停止重试。")
                with open(args.log_file, 'a') as main_log:
                    with open(log_tmp, 'r', errors='replace') as tmp_log:
                        main_log.write(tmp_log.read())
                os.remove(log_tmp)
                return 1
            last_fix_applied = "fix_download_failure"
            if fix_download_failure(log_tmp):
                fix_applied_this_iteration = 1
                print("修复已应用，准备下一次编译尝试。")
            else:
                print("修复下载失败错误失败，停止重试。")
                with open(args.log_file, 'a') as main_log:
                    with open(log_tmp, 'r', errors='replace') as tmp_log:
                        main_log.write(tmp_log.read())
                os.remove(log_tmp)
                return 1
        
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
        
        elif ("Collected errors:" in log_content or "ERROR: " in log_content) and metadata_fixed == 0:
            print("检测到可能的元数据错误...")
            last_fix_applied = "fix_metadata"
            if fix_metadata_errors():
                fix_applied_this_iteration = 1
                metadata_fixed = 1
        
        elif has_error:
            matched_pattern = re.search(args.error_pattern, log_content, re.MULTILINE)
            if matched_pattern:
                print(f"检测到通用错误模式: {matched_pattern.group(0)}")
            if last_fix_applied == "fix_generic" and fix_applied_this_iteration == 0:
                print("上次已尝试通用修复但无效果，停止重试。")
                with open(args.log_file, 'a') as main_log:
                    with open(log_tmp, 'r', errors='replace') as tmp_log:
                        main_log.write(tmp_log.read())
                os.remove(log_tmp)
                return 1
            print("未找到特定修复程序，将重试编译一次。")
            last_fix_applied = "fix_generic_retry"
        
        else:
            print(f"未检测到已知或通用的错误模式，但编译失败 (退出码: {compile_status})。")
            with open(args.log_file, 'a') as main_log:
                with open(log_tmp, 'r', errors='replace') as tmp_log:
                    main_log.write(tmp_log.read())
            os.remove(log_tmp)
            return 1
        
        if fix_applied_this_iteration == 0 and compile_status != 0:
            print(f"警告：检测到错误，但此轮未应用有效修复。上次尝试: {last_fix_applied or '无'}")
            if last_fix_applied == "fix_generic_retry" or retry_count >= (args.max_retry - 1):
                print("停止重试，因为未应用有效修复或已达重试上限。")
                with open(args.log_file, 'a') as main_log:
                    with open(log_tmp, 'r', errors='replace') as tmp_log:
                        main_log.write(tmp_log.read())
                os.remove(log_tmp)
                return 1
            else:
                print("将再重试一次，检查是否有其他可修复的错误出现。")
                last_fix_applied = "fix_generic_retry"
        
        os.remove(log_tmp)
        retry_count += 1
        print("等待 3 秒后重试...")
        time.sleep(3)
    
    print("--------------------------------------------------")
    print(f"达到最大重试次数 ({args.max_retry})，编译最终失败。")
    print("--------------------------------------------------")
    extract_error_block(args.log_file)
    print(f"请检查完整日志: {args.log_file}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
