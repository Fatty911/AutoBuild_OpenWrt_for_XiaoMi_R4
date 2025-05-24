#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
import re
import shutil
from pathlib import Path
import sys

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

def process_makefile_version_and_release(makefile_path: Path):
    """
    修复单个 Makefile 中的 PKG_VERSION 和 PKG_RELEASE 格式。
    - 移除 PKG_VERSION 的前导 'v'。
    - 确保 PKG_RELEASE 是正整数，如果缺失则添加 '1'。
    - 处理 PKG_VERSION 包含 release 部分的情况 (如 1.2.3-5)。
    """
    try:
        if makefile_path.is_symlink():
            try:
                real_path = makefile_path.resolve(strict=True)
                if not real_path.is_file(): return False
                makefile_path = real_path
            except Exception:
                if not makefile_path.exists(): return False

        if not makefile_path.is_file():
            return False

        with open(makefile_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        original_content = content
        current_content = content
        modified_in_file = False

        # Basic check if it looks like an OpenWrt package Makefile
        is_package_makefile = ('define Package/' in content and 'endef' in content) or \
                              ('include $(TOPDIR)/rules.mk' in content or \
                               'include $(INCLUDE_DIR)/package.mk' in content or \
                               'include ../../buildinfo.mk' in content)
        if not is_package_makefile:
            return False

        # --- Fix PKG_VERSION ---
        version_match = re.search(r'^(PKG_VERSION:=)(.*)$', current_content, re.MULTILINE)
        if version_match:
            current_version_line = version_match.group(0)
            current_version = version_match.group(2).strip()
            new_version = current_version

            # Simple fix: remove leading 'v' if present
            if new_version.startswith('v'):
                new_version = new_version.lstrip('v')
                if new_version != current_version:
                    print(f"  🔧 [{get_relative_path(str(makefile_path))}] 修正 PKG_VERSION: '{current_version}' -> '{new_version}'")
                    current_content = current_content.replace(current_version_line, f"PKG_VERSION:={new_version}", 1)
                    modified_in_file = True
                    current_version = new_version # Update for release check

        # --- Fix PKG_RELEASE ---
        release_match = re.search(r'^(PKG_RELEASE:=)(.*)$', current_content, re.MULTILINE)
        version_present = 'PKG_VERSION:=' in current_content

        new_release_val = None
        if release_match:
            current_release_line = release_match.group(0)
            current_release = release_match.group(2).strip()
            # Must be a positive integer
            if not current_release.isdigit() or int(current_release) <= 0:
                num_part = re.search(r'(\d+)$', current_release)
                if num_part:
                    new_release_val = num_part.group(1)
                    if int(new_release_val) <= 0: new_release_val = "1"
                else:
                    new_release_val = "1"

                if new_release_val != current_release:
                    print(f"  🔧 [{get_relative_path(str(makefile_path))}] 修正 PKG_RELEASE: '{current_release}' -> '{new_release_val}'")
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
                    print(f"  🔧 [{get_relative_path(str(makefile_path))}] 分离 PKG_VERSION/RELEASE: '{version_match_for_release.group(2)}{version_match_for_release.group(3) or ''}' -> VERSION='{base_version}', RELEASE='{release_part}'")
                    # Replace version line and insert release line after it
                    current_content = current_content.replace(current_version_line, f"{new_version_line}\n{new_release_line}", 1)
                    modified_in_file = True
                else:
                    # Version doesn't contain release, just add PKG_RELEASE:=1
                    new_release_line = "PKG_RELEASE:=1"
                    print(f"  🔧 [{get_relative_path(str(makefile_path))}] 添加缺失的 PKG_RELEASE:=1")
                    current_content = re.sub(r'^(PKG_VERSION:=.*)$', r'\1\n' + new_release_line, current_content, 1, re.MULTILINE)
                    modified_in_file = True
            else:
                new_release_line = "PKG_RELEASE:=1"
                print(f"  🔧 [{get_relative_path(str(makefile_path))}] 添加缺失的 PKG_RELEASE:=1 (Fallback)")
                current_content = re.sub(r'^(PKG_VERSION:=.*)$', r'\1\n' + new_release_line, current_content, 1, re.MULTILINE)
                modified_in_file = True

        if modified_in_file:
            with open(makefile_path, 'w', encoding='utf-8') as f:
                f.write(current_content)
            return True
        return False

    except Exception as e:
        if isinstance(e, UnicodeDecodeError):
            pass
        else:
            print(f"  ⚠️ 处理文件 {get_relative_path(str(makefile_path))} 时跳过，原因: {e}")
        return False

def process_makefile_depends(makefile_path: Path):
    """
    修复单个 Makefile 中的 DEPENDS 字段。
    - 移除版本约束 (如 >=, <=, =)。
    - 移除重复项 (对于非复杂 Make 语法)。
    - 优先保留 '@' 前缀的依赖项。
    """
    try:
        if makefile_path.is_symlink():
            try:
                real_path = makefile_path.resolve(strict=True)
                if not real_path.is_file(): return False
                makefile_path = real_path
            except Exception:
                if not makefile_path.exists(): return False

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

        depends_regex = r'^([ \t]*DEPENDS\s*[:+]?=\s*)((?:.*?\\\n)*.*)$'
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
            prefix = match.group(1)
            depends_value = match.group(2).replace('\\\n', ' ').strip()

            is_complex = '$' in depends_value or '(' in depends_value

            depends_list = re.split(r'\s+', depends_value)
            processed_depends = []
            needs_fix = False

            for dep in depends_list:
                dep = dep.strip()
                if not dep: continue

                original_dep_for_log = dep
                current_part = dep

                if not is_complex:
                    dep_prefix = ""
                    if dep.startswith('+') or dep.startswith('@'):
                        dep_prefix = dep[0]
                        dep_name = dep[1:]
                    else:
                        dep_name = dep

                    cleaned_name = re.split(r'[>=<~]', dep_name, 1)[0].strip()

                    if cleaned_name and re.match(r'^[a-zA-Z0-9._-]+$', cleaned_name):
                        current_part = f"{dep_prefix}{cleaned_name}"
                    elif cleaned_name:
                        current_part = None

                if current_part is not None:
                    processed_depends.append(current_part)

                if current_part != original_dep_for_log:
                    needs_fix = True

            if needs_fix:
                if is_complex:
                    new_depends_str = ' '.join(processed_depends)
                else:
                    seen = {}
                    unique_depends = []
                    for item in processed_depends:
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

                new_depends_line = f"{prefix}{new_depends_str}"

                current_block_in_new_content = new_content[start_index:end_index]

                if current_block_in_new_content == original_depends_line_block:
                    new_content = new_content[:start_index] + new_depends_line + new_content[end_index:]
                    offset_adjustment += len(new_depends_line) - len(original_depends_line_block)
                    modified_in_file = True
                else:
                    try:
                        current_start_index = new_content.index(original_depends_line_block, max(0, start_index - 100))
                        current_end_index = current_start_index + len(original_depends_line_block)
                        print(f"  ⚠️ 内容偏移，尝试基于原始内容在 {current_start_index} 处替换...文件: {get_relative_path(str(makefile_path))}")
                        new_content = new_content[:current_start_index] + new_depends_line + new_content[current_end_index:]
                        offset_adjustment = len(new_content) - len(original_content)
                        modified_in_file = True
                    except ValueError:
                        print(f"  ❌ 无法在当前内容中重新定位原始块，跳过此 DEPENDS 行的替换。文件: {get_relative_path(str(makefile_path))}")

        if modified_in_file:
            print(f"  ✅ 已修改依赖项: {get_relative_path(str(makefile_path))}")
            with open(makefile_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            return True
        return False

    except Exception as e:
        if isinstance(e, UnicodeDecodeError):
            pass
        elif isinstance(e, FileNotFoundError):
            print(f"  ⚠️ 处理文件时未找到: {get_relative_path(str(makefile_path))}")
        else:
            print(f"  ⚠️ 处理文件 {get_relative_path(str(makefile_path))} 时发生错误: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description='OpenWrt Makefile 元数据和依赖修复脚本')
    parser.add_argument('--makefile', type=str, help='要修复的单个 Makefile 路径。如果未指定，则扫描所有相关 Makefile。')
    parser.add_argument('--fix-version', action='store_true', help='修复 PKG_VERSION 和 PKG_RELEASE 格式。')
    parser.add_argument('--fix-depends', action='store_true', help='修复 DEPENDS 字段格式 (移除版本约束和重复项)。')
    parser.add_argument('--all', action='store_true', help='同时修复版本和依赖格式。')
    args = parser.parse_args()

    if not args.fix_version and not args.fix_depends and not args.all:
        print("请指定 --fix-version, --fix-depends 或 --all 来执行修复操作。")
        sys.exit(1)

    if args.all:
        args.fix_version = True
        args.fix_depends = True

    changed_count = 0
    # 忽略目录列表，避免扫描构建产物或无关文件
    ignore_dirs = ['build_dir', 'staging_dir', 'tmp', '.git', 'dl', 'bin', 'target', 'host'] 

    if args.makefile:
        makefile_path = Path(args.makefile)
        if not makefile_path.exists():
            print(f"错误: 指定的 Makefile '{args.makefile}' 不存在。")
            sys.exit(1)
        makefiles_to_process = [makefile_path]
        print(f"🎯 正在处理单个 Makefile: {get_relative_path(str(makefile_path))}")
    else:
        print("🔍 扫描所有相关 Makefile 文件...")
        all_makefiles = []
        for p in Path('.').rglob('Makefile'):
            # 检查路径是否包含任何忽略目录
            if not any(ignored in p.parts for ignored in ignore_dirs):
                all_makefiles.append(p)
        makefiles_to_process = all_makefiles
        print(f"找到 {len(makefiles_to_process)} 个潜在的 Makefile 文件进行检查。")

    processed_count = 0
    for makefile in makefiles_to_process:
        processed_count += 1
        if processed_count % 500 == 0: # 每处理500个文件报告一次进度
            print(f"已检查 {processed_count}/{len(makefiles_to_process)} 文件...")

        file_modified = False
        if args.fix_version:
            if process_makefile_version_and_release(makefile):
                file_modified = True
        if args.fix_depends:
            if process_makefile_depends(makefile):
                file_modified = True

        if file_modified:
            changed_count += 1

    if changed_count > 0:
        print(f"✅ 修复完成，共修改 {changed_count} 个 Makefile 文件。")
        sys.exit(0)
    else:
        print("ℹ️ 未发现需要修复的 Makefile 文件。")
        sys.exit(0)

if __name__ == "__main__":
    main()
