#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
import re
import shutil
from pathlib import Path
import sys

def get_relative_path(path_obj):
    """获取相对路径，优先相对于当前工作目录"""
    current_pwd = Path(os.getcwd())
    try:
        # Ensure path is absolute first
        abs_path = Path(path_obj).resolve()
        # Check if it's within the current working directory
        if abs_path.is_relative_to(current_pwd):
            return str(abs_path.relative_to(current_pwd))
        else:
            # Return absolute path if outside CWD
            return str(abs_path)
    except (ValueError, OSError, Exception) as e: # Handle various errors like non-existence or cross-drive issues
        # Fallback to the original path string if resolution/relpath fails
        # print(f"  DEBUG: Failed to get relative path for {path_obj}: {e}", file=sys.stderr) # Optional debug
        return str(path_obj)

def is_structurally_complex_item(item_str: str) -> bool:
    """Check if a dependency item string contains Makefile-specific complex syntax like variables or functions."""
    return '$' in item_str or '(' in item_str or '{' in item_str

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
                if not real_path.is_file():
                    print(f"  ⚠️ Symlink {get_relative_path(makefile_path)} does not point to a valid file. Skipping.", file=sys.stderr)
                    return False
                makefile_path = real_path
            except FileNotFoundError:
                print(f"  ⚠️ Symlink {get_relative_path(makefile_path)} points to a non-existent file. Skipping.", file=sys.stderr)
                return False
            except Exception as e:
                print(f"  ⚠️ Error resolving symlink {get_relative_path(makefile_path)}: {e}. Skipping.", file=sys.stderr)
                if not makefile_path.exists(): return False # Original check, keep for safety

        if not makefile_path.is_file():
            # This case should ideally be caught by the caller or initial scan
            # print(f"  DEBUG: Path {get_relative_path(makefile_path)} is not a file in process_makefile_version_and_release.", file=sys.stderr)
            return False

        try:
            with open(makefile_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
        except UnicodeDecodeError as e:
            print(f"  ⚠️ [{get_relative_path(makefile_path)}] Skipping due to UnicodeDecodeError: {e}. Try checking file encoding.", file=sys.stderr)
            return False
        except Exception as e: # Catch other read errors
            print(f"  ⚠️ [{get_relative_path(makefile_path)}] Error reading file: {e}. Skipping.", file=sys.stderr)
            return False

        original_content = content
        current_content = content
        modified_in_file = False

        is_package_makefile = ('define Package/' in content and 'endef' in content) or \
                              ('include $(TOPDIR)/rules.mk' in content or \
                               'include $(INCLUDE_DIR)/package.mk' in content or \
                               'include ../../buildinfo.mk' in content or \
                               '$(eval $(call BuildPackage))' in content) # Added common OpenWrt call
        if not is_package_makefile:
            return False

        # --- Fix PKG_VERSION ---
        version_match = re.search(r'^(PKG_VERSION\s*:=)(.*)$', current_content, re.MULTILINE)
        if version_match:
            current_version_line = version_match.group(0)
            current_version_val_raw = version_match.group(2)
            # Remove potential comments before stripping whitespace
            current_version_val = re.sub(r'\s*#.*$', '', current_version_val_raw).strip()
            new_version_val = current_version_val

            if new_version_val.startswith('v'):
                new_version_val = new_version_val.lstrip('v')
                if new_version_val != current_version_val: # Check if change actually happened
                    print(f"  🔧 [{get_relative_path(makefile_path)}] 修正 PKG_VERSION: '{current_version_val}' -> '{new_version_val}'")
                    # Reconstruct the line carefully to preserve original spacing and comments after value
                    new_version_line = f"{version_match.group(1)}{new_version_val}{current_version_val_raw[len(current_version_val_raw.rstrip()):]}"
                    # Preserve comment if it existed after the value part that was stripped.
                    # This is tricky. A simpler, more robust replace if formatting is standard:
                    current_content = current_content.replace(current_version_line, f"{version_match.group(1)}{new_version_val}", 1)
                    modified_in_file = True
                    current_version_val = new_version_val # Update for release check

        # --- Fix PKG_RELEASE ---
        release_match = re.search(r'^(PKG_RELEASE\s*:=)(.*)$', current_content, re.MULTILINE)
        version_present = 'PKG_VERSION\s*:=' in current_content # Use regex for robustness

        new_release_val_str = None # String representation of the new release number
        if release_match:
            current_release_line = release_match.group(0)
            current_release_val_raw = release_match.group(2)
            current_release_val = re.sub(r'\s*#.*$', '', current_release_val_raw).strip()

            if not current_release_val.isdigit() or int(current_release_val) <= 0:
                num_part_match = re.search(r'(\d+)$', current_release_val)
                if num_part_match:
                    temp_release_num = num_part_match.group(1)
                    if int(temp_release_num) > 0:
                        new_release_val_str = temp_release_num
                    else:
                        new_release_val_str = "1"
                else:
                    new_release_val_str = "1"

                if new_release_val_str != current_release_val:
                    print(f"  🔧 [{get_relative_path(makefile_path)}] 修正 PKG_RELEASE: '{current_release_val}' -> '{new_release_val_str}'")
                    current_content = current_content.replace(current_release_line, f"{release_match.group(1)}{new_release_val_str}", 1)
                    modified_in_file = True
        elif version_present: # PKG_RELEASE is missing, PKG_VERSION is present
            # Try to extract from PKG_VERSION like "1.2.3-5"
            # Need to re-fetch version_match with the potentially updated current_content
            version_match_for_release = re.search(r'^(PKG_VERSION\s*:=)(.*?)(-(\d+))?(\s*#.*)?$', current_content, re.MULTILINE)
            # The current_version_val already holds the (potentially 'v'-stripped) version

            release_from_version_val = None
            base_version_val = current_version_val # current_version_val is already stripped of 'v'

            # Check if current_version_val (which is already cleaned) contains a release part
            version_release_split_match = re.match(r'^(.*?)-(\d+)$', current_version_val)
            if version_release_split_match:
                base_version_val = version_release_split_match.group(1)
                potential_release_part = version_release_split_match.group(2)
                if potential_release_part.isdigit() and int(potential_release_part) > 0:
                    release_from_version_val = potential_release_part

            if release_from_version_val:
                # PKG_VERSION had release, split it
                # Find the PKG_VERSION line again in current_content to modify it
                # This assumes PKG_VERSION line was like PKG_VERSION:=<base_version>-<release_from_version_val>
                # We need to find the full original line of PKG_VERSION to replace it
                # The original version_match is on the original content, but if PKG_VERSION was modified (e.g. 'v' removed)
                # its line in current_content is different.
                # Best to find the current PKG_VERSION line:
                current_pkg_version_line_match = re.search(r'^(PKG_VERSION\s*:=.*)$', current_content, re.MULTILINE)
                if current_pkg_version_line_match:
                    the_pkg_version_line_to_replace = current_pkg_version_line_match.group(1)
                    new_version_line_content = f"PKG_VERSION:={base_version_val}"
                    new_release_line_content = f"PKG_RELEASE:={release_from_version_val}"
                    print(f"  🔧 [{get_relative_path(makefile_path)}] 分离 PKG_VERSION/RELEASE: '{current_version_val}' -> VERSION='{base_version_val}', RELEASE='{release_from_version_val}'")
                    replacement_block = f"{new_version_line_content}\n{new_release_line_content}"
                    current_content = current_content.replace(the_pkg_version_line_to_replace, replacement_block, 1)
                    modified_in_file = True
                else: # Should not happen if version_present and current_version_val is set
                    print(f"  ⚠️ [{get_relative_path(makefile_path)}] 无法定位 PKG_VERSION 行以分离 release。将添加默认 PKG_RELEASE:=1。")
                    new_release_line_content = "PKG_RELEASE:=1"
                    # Insert after the found PKG_VERSION line
                    current_content = re.sub(r'^(PKG_VERSION\s*:=.*)$', rf'\1\n{new_release_line_content}', current_content, 1, re.MULTILINE)
                    modified_in_file = True

            else:
                # Version doesn't contain release, just add PKG_RELEASE:=1
                new_release_line_content = "PKG_RELEASE:=1"
                print(f"  🔧 [{get_relative_path(makefile_path)}] 添加缺失的 PKG_RELEASE:=1")
                # Insert after the found PKG_VERSION line
                current_content = re.sub(r'^(PKG_VERSION\s*:=.*)$', rf'\1\n{new_release_line_content}', current_content, 1, re.MULTILINE)
                modified_in_file = True

        if modified_in_file:
            if current_content != original_content: # Ensure content actually changed
                with open(makefile_path, 'w', encoding='utf-8') as f:
                    f.write(current_content)
                return True
        return False

    except Exception as e:
        # Catchall for unexpected issues in this function
        print(f"  ⚠️ 处理 PKG_VERSION/RELEASE 在文件 {get_relative_path(makefile_path)} 时跳过，原因: {e}", file=sys.stderr)
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
                if not real_path.is_file():
                    print(f"  ⚠️ Symlink {get_relative_path(makefile_path)} does not point to a valid file. Skipping.", file=sys.stderr)
                    return False
                makefile_path = real_path
            except FileNotFoundError:
                print(f"  ⚠️ Symlink {get_relative_path(makefile_path)} points to a non-existent file. Skipping.", file=sys.stderr)
                return False
            except Exception as e:
                print(f"  ⚠️ Error resolving symlink {get_relative_path(makefile_path)}: {e}. Skipping.", file=sys.stderr)
                if not makefile_path.exists(): return False

        if not makefile_path.is_file():
            return False

        try:
            with open(makefile_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
        except UnicodeDecodeError as e:
            print(f"  ⚠️ [{get_relative_path(makefile_path)}] Skipping DEPENDS processing due to UnicodeDecodeError: {e}. Check file encoding.", file=sys.stderr)
            return False
        except Exception as e: # Catch other read errors
            print(f"  ⚠️ [{get_relative_path(makefile_path)}] Error reading file for DEPENDS processing: {e}. Skipping.", file=sys.stderr)
            return False

        original_content = content

        is_package_makefile = ('define Package/' in content and 'endef' in content) or \
                              ('include $(TOPDIR)/rules.mk' in content or \
                               'include $(INCLUDE_DIR)/package.mk' in content or \
                               'include ../../buildinfo.mk' in content or \
                               '$(eval $(call BuildPackage))' in content)
        if not is_package_makefile:
            return False

        # Regex for DEPENDS, accounts for += and := as well, and multi-line via \
        depends_regex = r'^([ \t]*(?:DEPENDS|DEPENDS_HOST)\s*[:+]?=\s*)((?:.*?\\\n)*.*)$'
        file_level_modified_flag = False
        new_content = content
        offset_adjustment = 0

        # Iterate over a static list of matches from the original content
        matches = list(re.finditer(depends_regex, content, re.MULTILINE | re.IGNORECASE))
        if not matches:
            return False

        for match_obj in matches:
            # Adjust start/end based on modifications from previous DEPENDS blocks in the same file
            current_match_start_offset = match_obj.start() + offset_adjustment
            current_match_end_offset = match_obj.end() + offset_adjustment

            original_depends_line_block = match_obj.group(0) # From original content
            
            # Get the block from potentially modified new_content using adjusted offsets
            # This is critical if prior replacements changed lengths
            # However, if content was replaced using string.replace on new_content directly,
            # then original_depends_line_block (from original content) might not be what's currently at these offsets.
            # A safer way is to re-find or use original_depends_line_block for replacement if still present.

            prefix_group = match_obj.group(1)
            depends_value_raw = match_obj.group(2)
            
            # Handle line continuations and remove comments from the whole value block first
            # A simple EOL comment removal; won't handle comments after '\' on the same physical line.
            depends_value_no_line_breaks = depends_value_raw.replace('\\\n', ' ')
            depends_value_cleaned_comments = re.sub(r'\s*#.*', '', depends_value_no_line_breaks, flags=re.MULTILINE).strip() # applied to whole block

            original_depends_for_log = depends_value_cleaned_comments # For logging comparison

            # Check if the DEPENDS line itself contains complex Makefile syntax
            is_line_structurally_complex = is_structurally_complex_item(depends_value_cleaned_comments)

            depends_items_list_raw = re.split(r'\s+', depends_value_cleaned_comments)
            processed_dependency_items = []
            items_were_modified = False

            for item_str_raw in depends_items_list_raw:
                item_str = item_str_raw.strip()
                if not item_str:
                    continue

                original_item_for_comparison = item_str # Store item after initial strip
                current_processed_item = item_str  # Start with current item

                item_prefix_char = ""
                item_name_part = item_str
                if item_str.startswith('+') or item_str.startswith('@'):
                    item_prefix_char = item_str[0]
                    item_name_part = item_str[1:]

                # Attempt to remove version constraints (e.g., >=1.0, =1.2.3, ~2.0)
                # This regex splits 'name' from '[operator]version'
                # It's applied to item_name_part, which is item_str without its +/@ prefix.
                # Example: item_name_part = "libfoo>=1.0" or "libbar-=1.2" (though -= is not typical for openwrt depends)
                name_parts = re.split(r'[>=<~]', item_name_part, 1)
                cleaned_name_candidate = name_parts[0].strip()

                # If a split happened (version constraint was present) AND cleaned_name is not empty
                if len(name_parts) > 1 and cleaned_name_candidate:
                    # A version constraint was likely removed
                    pass
                elif len(name_parts) > 1 and not cleaned_name_candidate:
                    # Item was likely just a version constraint (e.g., ">=1.0"), resulted in empty name.
                    pass # Will be filtered out if empty
                else:
                    # No version constraint found by split, or name part was already clean.
                    # cleaned_name_candidate remains as item_name_part.strip() via name_parts[0].strip()
                    pass


                # Validate the cleaned_name_candidate only if the original item_name_part wasn't complex
                # And if cleaned_name_candidate is not empty
                if cleaned_name_candidate:
                    if not is_structurally_complex_item(item_name_part) and \
                       not re.match(r'^[a-zA-Z0-9._~+-]+$', cleaned_name_candidate): # Allow + for things like libstdcpp++
                        print(f"    ⚠️ [{get_relative_path(makefile_path)}] Item '{item_str}' from DEPENDS resulted in invalid simple name '{cleaned_name_candidate}'. Reverting this item to '{item_name_part}'.")
                        cleaned_name_candidate = item_name_part # Revert to name before version strip for this item
                    # If it's structurally complex, we accept cleaned_name_candidate (which might still contain $,( etc.)
                    # e.g. if item_name_part was `$(PKG_NAME)-lib>=1.0`, cleaned_name_candidate is `$(PKG_NAME)-lib`
                
                if cleaned_name_candidate: # If name is not empty after cleaning
                    current_processed_item = f"{item_prefix_char}{cleaned_name_candidate}"
                elif item_prefix_char: # Name became empty, but had a prefix e.g. "+ >=1.0" -> "+"
                    current_processed_item = item_prefix_char
                else: # Became completely empty
                    current_processed_item = ""


                if current_processed_item != original_item_for_comparison:
                    items_were_modified = True
                    if original_item_for_comparison : # Avoid logging if original was also empty
                         print(f"    🔧 [{get_relative_path(makefile_path)}] DEPENDS item: '{original_item_for_comparison}' -> '{current_processed_item or '(removed)'}'")


                if current_processed_item: # Add if not empty
                    processed_dependency_items.append(current_processed_item)
                elif original_item_for_comparison: # Log if a non-empty item was removed
                    items_were_modified = True # Removal is a modification

            final_dependency_string = ""
            # Apply de-duplication only if the line was not complex and items were modified or could be de-duplicated
            if is_line_structurally_complex:
                final_dependency_string = ' '.join(processed_dependency_items)
                if final_dependency_string != original_depends_for_log:
                     items_were_modified = True # Ensure flag is set if string differs
                else:
                     items_were_modified = False # No actual change
            else: # Not a complex line, apply de-duplication
                # Original de-duplication logic (seems robust for its purpose)
                seen_names = {} # Maps item_name to its preferred prefix
                unique_deps_ordered = []
                
                temp_final_items = {} # name -> item_with_best_prefix
                # First pass: determine the best representation for each name
                for item in processed_dependency_items:
                    dep_prefix = ""
                    dep_name = item
                    if item.startswith('+') or item.startswith('@'):
                        dep_prefix = item[0]
                        dep_name = item[1:]
                    
                    if not dep_name: # Handle standalone prefix like "+" or "@"
                        if dep_prefix and dep_prefix not in temp_final_items: # Add standalone prefix once
                            temp_final_items[dep_prefix] = dep_prefix # Use prefix as key for itself
                        continue

                    if dep_name not in temp_final_items:
                        temp_final_items[dep_name] = item
                    else:
                        existing_item = temp_final_items[dep_name]
                        existing_prefix = ""
                        if existing_item.startswith('+') or existing_item.startswith('@'):
                            existing_prefix = existing_item[0]
                        
                        # Prefer @ over +, prefer + over no-prefix
                        if dep_prefix == '@':
                            temp_final_items[dep_name] = item
                        elif dep_prefix == '+' and existing_prefix == '':
                            temp_final_items[dep_name] = item
                
                # Second pass: build the unique_deps_ordered list, maintaining relative order of first appearance
                added_names_to_final_list = set()
                for item in processed_dependency_items: # Iterate original processed items for order
                    dep_prefix = ""
                    dep_name = item
                    if item.startswith('+') or item.startswith('@'):
                        dep_prefix = item[0]
                        dep_name = item[1:]

                    key_for_lookup = dep_name if dep_name else dep_prefix # Use name or prefix (if standalone) as key

                    if key_for_lookup and key_for_lookup not in added_names_to_final_list:
                        if key_for_lookup in temp_final_items: # Ensure it was processed and stored
                            unique_deps_ordered.append(temp_final_items[key_for_lookup])
                            added_names_to_final_list.add(key_for_lookup)
                        # Else: item was empty or became problematic, already handled

                final_dependency_string = ' '.join(unique_deps_ordered)
                if final_dependency_string != original_depends_for_log:
                    items_were_modified = True
                elif not items_were_modified and len(processed_dependency_items) != len(unique_deps_ordered): # Only dedup happened
                    items_were_modified = True # De-duplication itself is a change
                elif final_dependency_string == original_depends_for_log and items_were_modified: # items were modified but resulted in same string after dedup
                    pass # Keep items_were_modified as True if individual items changed formatting
                else: # No change to items, and no change from de-duplication
                    items_were_modified = False


            if items_were_modified:
                new_depends_line_content = f"{prefix_group}{final_dependency_string}"
                
                # Robustly find and replace the block in new_content
                # Option 1: If original_depends_line_block is guaranteed to be unique and unchanged before this match
                try:
                    # Try to find the exact original block to replace, using a limited search window for safety
                    # This is safer if multiple identical DEPENDS lines exist, but relies on original_content.
                    # `new_content` is the accumulator of changes.
                    # We need to replace in `new_content` at the correct, adjusted location.
                    block_in_current_new_content = new_content[current_match_start_offset : current_match_end_offset]

                    if block_in_current_new_content == original_depends_line_block: # Check if the content at offset is still the original one
                        new_content = new_content[:current_match_start_offset] + new_depends_line_content + new_content[current_match_end_offset:]
                        offset_adjustment += len(new_depends_line_content) - len(original_depends_line_block)
                        file_level_modified_flag = True
                    else:
                        # Fallback: try to find the original_depends_line_block string in new_content
                        # This might be risky if the block is not unique or has been subtly changed by prior edits.
                        # A more robust way would be to always work from original_content for matches and build a new list of lines.
                        # For now, using index() as a fallback.
                        print(f"  ⚠️ [{get_relative_path(makefile_path)}] Content offset mismatch for DEPENDS. Trying to locate original block string for replacement.")
                        try:
                            # Search for the original block in the current state of new_content
                            # This is only safe if original_depends_line_block is very unique
                            # A windowed search might be better:
                            # search_start = max(0, current_match_start_offset - 100)
                            # search_end = min(len(new_content), current_match_end_offset + 100)
                            # actual_start_index_in_new = new_content.index(original_depends_line_block, search_start, search_end )
                            actual_start_index_in_new = new_content.index(original_depends_line_block) # Simpler but riskier
                            actual_end_index_in_new = actual_start_index_in_new + len(original_depends_line_block)
                            
                            new_content = new_content[:actual_start_index_in_new] + new_depends_line_content + new_content[actual_end_index_in_new:]
                            # After this, offset_adjustment based on original content is invalid.
                            # Best to recalculate full length diff if this path is taken often.
                            offset_adjustment = len(new_content) - len(original_content) # Recalculate full offset
                            file_level_modified_flag = True
                            print(f"    ✅ [{get_relative_path(makefile_path)}] Fallback replacement successful for a DEPENDS block.")
                        except ValueError:
                            print(f"  ❌ [{get_relative_path(makefile_path)}] Failed to replace DEPENDS block: Original block not found in current content. Skipping this specific DEPENDS modification.")
                            # Continue to next match, but this DEPENDS block is not changed.
                except Exception as e_replace:
                     print(f"  ❌ [{get_relative_path(makefile_path)}] Error during DEPENDS block replacement: {e_replace}. Skipping this specific DEPENDS modification.")


        if file_level_modified_flag and new_content != original_content:
            print(f"  ✅ Successfully modified DEPENDS in: {get_relative_path(makefile_path)}")
            with open(makefile_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            return True
        return file_level_modified_flag # Return true if any modification attempt was made, even if content didn't change due to idempotency

    except FileNotFoundError:
        # This should ideally be caught by the caller's loop if makefile_path doesn't exist initially
        print(f"  ⚠️ File not found during DEPENDS processing: {get_relative_path(makefile_path)}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"  ⚠️ Processing DEPENDS in {get_relative_path(makefile_path)} failed: {e}", file=sys.stderr)
        return False

def main():
    parser = argparse.ArgumentParser(description='OpenWrt Makefile 元数据和依赖修复脚本')
    parser.add_argument('--makefile', type=str, help='要修复的单个 Makefile 路径。如果未指定，则扫描所有相关 Makefile。')
    parser.add_argument('--fix-version', action='store_true', help='修复 PKG_VERSION 和 PKG_RELEASE 格式。')
    parser.add_argument('--fix-depends', action='store_true', help='修复 DEPENDS 字段格式 (移除版本约束和重复项)。')
    parser.add_argument('--all', action='store_true', help='同时修复版本和依赖格式。')
    args = parser.parse_args()

    if not args.fix_version and not args.fix_depends and not args.all:
        print("请指定 --fix-version, --fix-depends 或 --all 来执行修复操作。使用 --help 获取帮助。")
        sys.exit(1)

    if args.all:
        args.fix_version = True
        args.fix_depends = True

    changed_files_count = 0
    # 忽略目录列表，避免扫描构建产物或无关文件
    # Added 'node_modules' as it often contains many Makefiles not relevant to OpenWrt core packages
    ignore_dirs = ['build_dir', 'staging_dir', 'tmp', '.git', 'dl', 'bin', 'target', 'host', 'node_modules', '.svn', '.hg']

    makefiles_to_process = []
    if args.makefile:
        makefile_path_arg = Path(args.makefile)
        if not makefile_path_arg.exists():
            print(f"错误: 指定的 Makefile '{args.makefile}' 不存在。", file=sys.stderr)
            sys.exit(1)
        if not makefile_path_arg.is_file():
            print(f"错误: 指定的路径 '{args.makefile}' 不是一个文件。", file=sys.stderr)
            sys.exit(1)
        makefiles_to_process = [makefile_path_arg]
        print(f"🎯 正在处理单个 Makefile: {get_relative_path(makefile_path_arg)}")
    else:
        print("🔍 扫描所有相关 Makefile 文件 (这可能需要一些时间)...")
        # Using current directory as base for rglob
        base_path = Path('.')
        all_found_makefiles = []
        try:
            for p in base_path.rglob('Makefile'): # Case-sensitive, common for Makefiles
                # Check if any part of the path is in ignore_dirs
                if not any(ignored_dir in p.parts for ignored_dir in ignore_dirs):
                    all_found_makefiles.append(p)
            # Consider also rglob('makefile') if case-insensitivity is needed, though less common for OpenWrt
        except Exception as e:
            print(f"Error during Makefile scanning: {e}", file=sys.stderr)
            sys.exit(1)
            
        makefiles_to_process = all_found_makefiles
        print(f"找到 {len(makefiles_to_process)} 个潜在的 Makefile 文件进行检查。")

    processed_count = 0
    total_files = len(makefiles_to_process)

    for makefile_path_obj in makefiles_to_process:
        processed_count += 1
        if processed_count % 200 == 0 or processed_count == total_files: # Report progress
            print(f"已检查 {processed_count}/{total_files} 文件... ({get_relative_path(makefile_path_obj)})")

        file_actually_modified_this_run = False
        try:
            # Resolve symlinks and ensure it's a file before passing to processors
            current_target_path = makefile_path_obj
            if makefile_path_obj.is_symlink():
                try:
                    current_target_path = makefile_path_obj.resolve(strict=True)
                except FileNotFoundError:
                    print(f"  ℹ️ Symlink {get_relative_path(makefile_path_obj)} points to a non-existent file. Skipping.", file=sys.stderr)
                    continue # Skip this symlink
                except Exception as e_resolve:
                    print(f"  ⚠️ Error resolving symlink {get_relative_path(makefile_path_obj)}: {e_resolve}. Skipping.", file=sys.stderr)
                    continue

            if not current_target_path.is_file():
                # print(f"  DEBUG: Skipped {get_relative_path(current_target_path)} as it's not a file (or symlink to file).", file=sys.stderr)
                continue

            made_version_changes = False
            made_depends_changes = False

            if args.fix_version:
                if process_makefile_version_and_release(current_target_path): # Pass resolved path
                    made_version_changes = True
            
            if args.fix_depends:
                # process_makefile_depends might need to re-read the file if fix_version changed it.
                # For simplicity, current script has them operate independently on the file state when called.
                # If both are true, process_makefile_depends will see changes from process_makefile_version_and_release.
                if process_makefile_depends(current_target_path): # Pass resolved path
                    made_depends_changes = True
            
            if made_version_changes or made_depends_changes:
                file_actually_modified_this_run = True

        except Exception as e_main_loop:
            print(f"  💥 处理文件 {get_relative_path(makefile_path_obj)} 时发生未预料的错误: {e_main_loop}", file=sys.stderr)
            # Continue to the next file

        if file_actually_modified_this_run:
            changed_files_count += 1

    print("-" * 30)
    if changed_files_count > 0:
        print(f"✅ 修复完成，共修改 {changed_files_count} 个 Makefile 文件。")
    else:
        print("ℹ️ 未发现需要修复的 Makefile 文件，或者文件已经是正确的格式。")
    sys.exit(0)

if __name__ == "__main__":
    main()
