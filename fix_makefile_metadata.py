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
        abs_path = Path(path_obj).resolve()
        if abs_path.is_relative_to(current_pwd):
            return str(abs_path.relative_to(current_pwd))
        else:
            return str(abs_path)
    except (ValueError, OSError, Exception):
        return str(path_obj)

def is_structurally_complex_item(item_str: str) -> bool:
    """Check if a dependency item string contains Makefile-specific complex syntax like variables or functions."""
    return '$' in item_str or '(' in item_str or '{' in item_str

def process_makefile_version_and_release(makefile_path: Path):
    """
    修复单个 Makefile 中的 PKG_VERSION 和 PKG_RELEASE 格式。
    """
    relative_makefile_path = get_relative_path(makefile_path)
    # print(f"  ℹ️ [VERSION/RELEASE] Processing: {relative_makefile_path}") # Verbose logging
    try:
        if makefile_path.is_symlink():
            try:
                real_path = makefile_path.resolve(strict=True)
                if not real_path.is_file():
                    # print(f"  ⚠️ [VERSION/RELEASE] Symlink {relative_makefile_path} does not point to a valid file. Skipping.", file=sys.stderr)
                    return False
                makefile_path = real_path
                relative_makefile_path = get_relative_path(makefile_path)
            except FileNotFoundError:
                # print(f"  ⚠️ [VERSION/RELEASE] Symlink {relative_makefile_path} points to a non-existent file. Skipping.", file=sys.stderr)
                return False
            except Exception as e:
                # print(f"  ⚠️ [VERSION/RELEASE] Error resolving symlink {relative_makefile_path}: {e}. Skipping.", file=sys.stderr)
                if not makefile_path.exists(): return False

        if not makefile_path.is_file():
            return False

        try:
            with open(makefile_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
        except UnicodeDecodeError: # Simplified error logging for brevity
            # print(f"  ⚠️ [{relative_makefile_path}] [VERSION/RELEASE] Skipping due to UnicodeDecodeError.", file=sys.stderr)
            return False
        except Exception:
            # print(f"  ⚠️ [{relative_makefile_path}] [VERSION/RELEASE] Error reading file. Skipping.", file=sys.stderr)
            return False

        original_content = content
        current_content = content
        modified_in_file = False

        is_package_makefile = ('define Package/' in content and 'endef' in content) or \
                              ('include $(TOPDIR)/rules.mk' in content or \
                               'include $(INCLUDE_DIR)/package.mk' in content or \
                               'include ../../buildinfo.mk' in content or \
                               '$(eval $(call BuildPackage))' in content)
        if not is_package_makefile:
            # print(f"  ℹ️ [{relative_makefile_path}] [VERSION/RELEASE] Not a recognized OpenWrt package Makefile. Skipping.")
            return False

        version_match = re.search(r'^(PKG_VERSION\s*:=)(.*)$', current_content, re.MULTILINE)
        base_version_val = ""
        version_embedded_release = None
        original_pkg_version_line = ""
        original_pkg_version_value_str = ""

        if version_match:
            original_pkg_version_line = version_match.group(0)
            original_pkg_version_value_raw = version_match.group(2)
            original_pkg_version_value_str = re.sub(r'\s*#.*$', '', original_pkg_version_value_raw).strip()
            temp_version_val = original_pkg_version_value_str
            if temp_version_val.startswith('v'):
                temp_version_val = temp_version_val.lstrip('v')

            version_release_split_match = re.match(r'^(.*?)-(\d+)$', temp_version_val)
            if version_release_split_match:
                base_version_val = version_release_split_match.group(1)
                potential_release_part = version_release_split_match.group(2)
                if potential_release_part.isdigit() and int(potential_release_part) > 0:
                    version_embedded_release = potential_release_part
            else:
                base_version_val = temp_version_val
        else: # No PKG_VERSION found, nothing to do for version/release logic
            return False


        release_match = re.search(r'^(PKG_RELEASE\s*:=)(.*)$', current_content, re.MULTILINE)
        final_pkg_release_val = "1"
        original_pkg_release_line = ""
        original_pkg_release_value_str = ""
        version_present_in_content = bool(version_match) # Re-check based on initial match

        if release_match:
            original_pkg_release_line = release_match.group(0)
            original_pkg_release_value_raw = release_match.group(2)
            original_pkg_release_value_str = re.sub(r'\s*#.*$', '', original_pkg_release_value_raw).strip()
            if original_pkg_release_value_str.isdigit() and int(original_pkg_release_value_str) > 0:
                final_pkg_release_val = original_pkg_release_value_str
            else: # Invalid existing PKG_RELEASE
                if version_embedded_release:
                    final_pkg_release_val = version_embedded_release
                # else final_pkg_release_val remains "1"
        elif version_embedded_release:
            final_pkg_release_val = version_embedded_release
        # else final_pkg_release_val remains "1"

        # Apply changes
        if base_version_val and (base_version_val != original_pkg_version_value_str): # original_pkg_version_value_str includes 'v' if present
            # Check if only 'v' was stripped and no release was split
            only_v_stripped = original_pkg_version_value_str.startswith('v') and \
                              base_version_val == original_pkg_version_value_str.lstrip('v') and \
                              not version_embedded_release
            
            actual_base_to_compare = original_pkg_version_value_str
            if original_pkg_version_value_str.startswith('v'): # Strip v for comparison if base_version_val is already stripped
                 actual_base_to_compare = original_pkg_version_value_str.lstrip('v')


            if base_version_val != actual_base_to_compare or only_v_stripped : # If base version changed OR only v was stripped
                new_pkg_version_line = f"PKG_VERSION:={base_version_val}"
                # print(f"    🔧 [{relative_makefile_path}] PKG_VERSION: Corrected to base: '{original_pkg_version_value_str}' -> '{base_version_val}'")
                current_content = current_content.replace(original_pkg_version_line, new_pkg_version_line, 1)
                modified_in_file = True

        if release_match:
            if final_pkg_release_val != original_pkg_release_value_str:
                new_pkg_release_line = f"PKG_RELEASE:={final_pkg_release_val}"
                # print(f"    🔧 [{relative_makefile_path}] PKG_RELEASE: Updated: '{original_pkg_release_value_str}' -> '{final_pkg_release_val}'")
                current_content = current_content.replace(original_pkg_release_line, new_pkg_release_line, 1)
                modified_in_file = True
        elif version_present_in_content: # PKG_RELEASE was not defined, add it
            new_pkg_release_line_to_add = f"PKG_RELEASE:={final_pkg_release_val}"
            current_pkg_version_line_for_insert = re.search(r'^(PKG_VERSION\s*:=.*)$', current_content, re.MULTILINE)
            if current_pkg_version_line_for_insert:
                line_to_insert_after = current_pkg_version_line_for_insert.group(1)
                # print(f"    🔧 [{relative_makefile_path}] PKG_RELEASE: Added: '{new_pkg_release_line_to_add}'")
                current_content = current_content.replace(line_to_insert_after, f"{line_to_insert_after}\n{new_pkg_release_line_to_add}", 1)
                modified_in_file = True

        if modified_in_file and current_content != original_content:
            # print(f"  💾 [{relative_makefile_path}] [VERSION/RELEASE] Saving changes.")
            with open(makefile_path, 'w', encoding='utf-8') as f:
                f.write(current_content)
            return True
        # else:
            # print(f"  ℹ️ [{relative_makefile_path}] [VERSION/RELEASE] No effective changes.")
        return False
    except Exception: # Simplified error logging
        # print(f"  ⚠️ [VERSION/RELEASE] Processing {relative_makefile_path} failed.", file=sys.stderr)
        return False

def smart_split_depends(depends_str: str):
    """
    Splits a dependency string, attempting to keep Makefile $(...) constructs as single items.
    This is a challenging parsing problem and this implementation is a heuristic.
    It might not cover all complex nested cases perfectly.
    """
    items = []
    current_item = ""
    paren_level = 0
    i = 0
    while i < len(depends_str):
        char = depends_str[i]
        if char == '$' and i + 1 < len(depends_str) and depends_str[i+1] == '(':
            current_item += char
            paren_level +=1
        elif char == '(' and paren_level > 0 : # Inside a $(...)
            current_item += char
            paren_level +=1
        elif char == ')' and paren_level > 0:
            current_item += char
            paren_level -= 1
        elif char.isspace() and paren_level == 0: # Space outside of $(...)
            if current_item:
                items.append(current_item)
                current_item = ""
        else: # Regular character or space inside $(...)
            current_item += char
        i += 1
    if current_item: # Add the last item
        items.append(current_item)
    return [item.strip() for item in items if item.strip()]


def process_generic_depends(makefile_path: Path, depends_var_names: list, context_name: str):
    """
    Generic function to process DEPENDS-like variables (DEPENDS, DEPENDS_HOST, LUCI_DEPENDS, etc.).
    """
    relative_makefile_path = get_relative_path(makefile_path)
    # print(f"  ℹ️ [{context_name}] Processing: {relative_makefile_path}") # Verbose
    try:
        if makefile_path.is_symlink(): # Standard symlink handling
            try:
                real_path = makefile_path.resolve(strict=True)
                if not real_path.is_file(): return False
                makefile_path = real_path
                relative_makefile_path = get_relative_path(makefile_path)
            except FileNotFoundError: return False
            except Exception: 
                if not makefile_path.exists(): return False
                return False # Other resolve errors

        if not makefile_path.is_file(): return False

        try:
            with open(makefile_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
        except UnicodeDecodeError: return False
        except Exception: return False

        original_content = content
        current_content = content
        file_level_modified_flag = False

        # Heuristic to check if it's a relevant Makefile
        is_relevant_makefile = ('define Package/' in content and 'endef' in content) or \
                               ('include $(TOPDIR)/rules.mk' in content or \
                                'include $(INCLUDE_DIR)/package.mk' in content or \
                                'include $(TOPDIR)/feeds/luci/luci.mk' in content or \
                                '$(eval $(call BuildPackage))' in content)
        if not is_relevant_makefile and "LUCI" not in context_name : # Allow LUCI specific even if not full package.mk
             # print(f"  ℹ️ [{relative_makefile_path}] [{context_name}] Not a recognized relevant Makefile. Skipping.")
             return False


        for dep_var_name in depends_var_names:
            # Regex for DEPENDS, LUCI_DEPENDS etc., accounts for += and :=, and multi-line via \
            # It captures the prefix (e.g., "DEPENDS:=") and the value part.
            depends_regex_str = r'^([ \t]*(?:' + re.escape(dep_var_name) + r')\s*[:+]?=\s*)((?:.*?\\\n)*.*)$'
            
            # Find all occurrences of this specific depends variable
            matches_for_current_var = list(re.finditer(depends_regex_str, current_content, re.MULTILINE | re.IGNORECASE))
            if not matches_for_current_var:
                # print(f"    ℹ️ [{relative_makefile_path}] [{dep_var_name}] Not found.")
                continue
            
            # print(f"    Found {len(matches_for_current_var)} instance(s) of {dep_var_name} in {relative_makefile_path}.")

            temp_content_for_var_processing = current_content # Work on a copy for this variable's blocks
            var_blocks_modified_count = 0
            
            # Iterate backwards to handle replacements in multi-block scenarios correctly
            for i, match_obj in reversed(list(enumerate(matches_for_current_var))):
                original_depends_line_block = match_obj.group(0)
                # print(f"    🔍 [{relative_makefile_path}] [{dep_var_name} Block {i+1}] Original: {original_depends_line_block.strip()}")

                prefix_group = match_obj.group(1)
                depends_value_raw = match_obj.group(2)
                
                depends_value_no_line_breaks = depends_value_raw.replace('\\\n', ' ')
                # Remove comments AFTER joining lines, but BEFORE smart_split
                depends_value_cleaned_comments = re.sub(r'\s*#.*', '', depends_value_no_line_breaks).strip()
                
                original_depends_value_for_log = depends_value_cleaned_comments

                # Use smart_split to handle $(...) constructs
                depends_items_list_raw = smart_split_depends(depends_value_cleaned_comments)
                
                processed_dependency_items = []
                items_were_modified_this_block = False

                for item_str_raw in depends_items_list_raw:
                    item_str = item_str_raw.strip() # smart_split should already strip
                    if not item_str:
                        continue

                    original_item_for_comparison = item_str
                    current_processed_item = item_str

                    if is_structurally_complex_item(item_str):
                        # For complex items (like $(if...)), do not attempt to strip version constraints from within.
                        # Just add it as is. The main goal is to prevent breaking these structures.
                        # print(f"        ℹ️ [{relative_makefile_path}] [{dep_var_name} Item] Preserving complex item: '{item_str}'")
                        processed_dependency_items.append(item_str)
                        continue # Move to next item

                    # --- For simple items (not Makefile constructs like $(...)) ---
                    item_prefix_char = ""
                    item_name_part = item_str
                    if item_str.startswith('+') or item_str.startswith('@'):
                        item_prefix_char = item_str[0]
                        item_name_part = item_str[1:]

                    # Remove version constraints (e.g., >=1.0, =1.2.3, ~2.0)
                    # Also handles cases like pkg(>=1.0) for LuCI depends
                    name_parts = re.split(r'[>=<~]', item_name_part, 1)
                    cleaned_name_candidate = name_parts[0].strip()
                    # Further clean stray parentheses if it's a LuCI dependency context
                    if "LUCI" in context_name:
                        cleaned_name_candidate = cleaned_name_candidate.replace('(', '').replace(')', '').strip()


                    if cleaned_name_candidate:
                        # Validate the cleaned_name_candidate (if not complex, which is already handled)
                        if not re.match(r'^[a-zA-Z0-9._~+-]+$', cleaned_name_candidate):
                            # print(f"        ⚠️ [{relative_makefile_path}] [{dep_var_name} Item] Invalid simple name '{cleaned_name_candidate}' from '{item_str}'. Reverting to '{item_name_part}'.")
                            cleaned_name_candidate = item_name_part # Revert to name before version strip
                        current_processed_item = f"{item_prefix_char}{cleaned_name_candidate}"
                    elif item_prefix_char: # Name became empty, but had a prefix
                        current_processed_item = item_prefix_char
                    else: # Became completely empty
                        current_processed_item = ""

                    if current_processed_item != original_item_for_comparison:
                        items_were_modified_this_block = True
                        # if original_item_for_comparison :
                            # print(f"        🔧 [{relative_makefile_path}] [{dep_var_name} Item] Cleaned: '{original_item_for_comparison}' -> '{current_processed_item or '(removed)'}'")

                    if current_processed_item:
                        processed_dependency_items.append(current_processed_item)
                    elif original_item_for_comparison: # Log if a non-empty item was removed
                        items_were_modified_this_block = True
                
                # De-duplication logic (applied to the list of processed items)
                temp_final_items = {}
                for item in processed_dependency_items:
                    dep_prefix = ""
                    dep_name = item
                    if item.startswith('+') or item.startswith('@'):
                        dep_prefix = item[0]
                        dep_name = item[1:]
                    
                    # Handle complex items as a whole for de-duplication key
                    key_for_dedup = item if is_structurally_complex_item(item) else (dep_name if dep_name else dep_prefix)

                    if not key_for_dedup: continue # Skip empty items

                    if key_for_dedup not in temp_final_items:
                        temp_final_items[key_for_dedup] = item
                    else: # Handle prefix preference for simple items
                        if not is_structurally_complex_item(item):
                            existing_item = temp_final_items[key_for_dedup]
                            existing_prefix = ""
                            if existing_item.startswith('+') or existing_item.startswith('@'):
                                existing_prefix = existing_item[0]
                            if dep_prefix == '@':
                                temp_final_items[key_for_dedup] = item
                            elif dep_prefix == '+' and existing_prefix == '':
                                temp_final_items[key_for_dedup] = item
                
                unique_deps_ordered = []
                added_keys_to_final_list = set()
                for item in processed_dependency_items: # Iterate original processed items for order
                    dep_prefix = ""
                    dep_name = item
                    if item.startswith('+') or item.startswith('@'):
                        dep_prefix = item[0]
                        dep_name = item[1:]
                    key_for_lookup = item if is_structurally_complex_item(item) else (dep_name if dep_name else dep_prefix)

                    if key_for_lookup and key_for_lookup not in added_keys_to_final_list:
                        if key_for_lookup in temp_final_items:
                            unique_deps_ordered.append(temp_final_items[key_for_lookup])
                            added_keys_to_final_list.add(key_for_lookup)
                
                final_dependency_string = ' '.join(unique_deps_ordered)

                if final_dependency_string != original_depends_value_for_log:
                    items_were_modified_this_block = True # If string differs after dedup/cleaning
                    # print(f"        🔧 [{relative_makefile_path}] [{dep_var_name} Block {i+1}] Value changed: '{original_depends_value_for_log}' -> '{final_dependency_string}'")
                elif not items_were_modified_this_block and len(processed_dependency_items) != len(unique_deps_ordered):
                    items_were_modified_this_block = True # Only dedup happened
                    # print(f"        🔧 [{relative_makefile_path}] [{dep_var_name} Block {i+1}] De-duplicated (only): '{original_depends_value_for_log}' -> '{final_dependency_string}'")


                if items_were_modified_this_block:
                    var_blocks_modified_count +=1
                    new_depends_line_content = f"{prefix_group}{final_dependency_string}"
                    # print(f"    ✅ [{relative_makefile_path}] [{dep_var_name} Block {i+1}] Finalized: {new_depends_line_content.strip()}")
                    
                    # Replace in temp_content_for_var_processing
                    # Since we iterate backwards, match.start() and match.end() are relative to original `current_content`
                    # but we modify `temp_content_for_var_processing` which is a snapshot at the start of this var's processing.
                    # This replacement needs to be on `current_content` directly if we want to avoid complex offset management.
                    # Let's try replacing on current_content directly.
                    current_content = current_content[:match_obj.start()] + new_depends_line_content + current_content[match_obj.end():]
                    file_level_modified_flag = True # Mark that at least one block for this var was changed in the file
                # else:
                    # print(f"    ℹ️ [{relative_makefile_path}] [{dep_var_name} Block {i+1}] No changes needed for this block.")
        
        # After processing all blocks for all specified dep_var_names
        if file_level_modified_flag and current_content != original_content:
            # print(f"  💾 [{relative_makefile_path}] [{context_name}] Saving changes.")
            with open(makefile_path, 'w', encoding='utf-8') as f:
                f.write(current_content)
            return True
        # elif file_level_modified_flag:
            # print(f"  ℹ️ [{relative_makefile_path}] [{context_name}] Modifications attempted but result is identical to original.")
        
        return False # No effective changes saved

    except FileNotFoundError: return False # Should be caught by initial checks
    except Exception: # Simplified error logging
        # print(f"  ⚠️ [{context_name}] Processing {relative_makefile_path} failed.", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description='OpenWrt Makefile 元数据和依赖修复脚本')
    parser.add_argument('--makefile', type=str, help='要修复的单个 Makefile 路径。如果未指定，则扫描所有相关 Makefile。')
    parser.add_argument('--fix-version', action='store_true', help='修复 PKG_VERSION 和 PKG_RELEASE 格式。')
    parser.add_argument('--fix-depends', action='store_true', help='修复 DEPENDS, LUCI_DEPENDS 等字段格式。')
    parser.add_argument('--all', action='store_true', help='同时修复版本和依赖格式。')
    args = parser.parse_args()

    if not args.fix_version and not args.fix_depends and not args.all:
        print("请指定 --fix-version, --fix-depends 或 --all 来执行修复操作。使用 --help 获取帮助。")
        sys.exit(1)

    if args.all:
        args.fix_version = True
        args.fix_depends = True

    changed_files_count = 0
    ignore_dirs = ['build_dir', 'staging_dir', 'tmp', '.git', 'dl', 'bin', 'target', 'host', 'node_modules', '.svn', '.hg']

    makefiles_to_process = []
    if args.makefile:
        makefile_path_arg = Path(args.makefile)
        if not makefile_path_arg.exists():
            print(f"错误: 指定的 Makefile '{get_relative_path(makefile_path_arg)}' 不存在。", file=sys.stderr)
            sys.exit(1)
        if not makefile_path_arg.is_file():
            print(f"错误: 指定的路径 '{get_relative_path(makefile_path_arg)}' 不是一个文件。", file=sys.stderr)
            sys.exit(1)
        makefiles_to_process = [makefile_path_arg]
        print(f"🎯 正在处理单个 Makefile: {get_relative_path(makefile_path_arg)}")
    else:
        print("🔍 扫描所有相关 Makefile 文件 (这可能需要一些时间)...")
        base_path = Path('.')
        all_found_makefiles = []
        try:
            for pattern in ['Makefile', 'makefile']: # Scan for both common names
                for p in base_path.rglob(pattern):
                    if not any(ignored_dir in p.parts for ignored_dir in ignore_dirs):
                        try:
                            resolved_p = p.resolve() # Resolve to handle symlinks and avoid duplicates on case-insensitive FS
                            if resolved_p not in [m.resolve() for m in all_found_makefiles if m.exists()]: # Check against resolved paths of existing found files
                                all_found_makefiles.append(p)
                        except Exception: # Handle broken symlinks etc. during resolve
                            if not p.exists() and p.is_symlink(): # Broken symlink
                                # print(f"  ℹ️ Skipping broken symlink: {get_relative_path(p)}", file=sys.stderr)
                                pass
                            else: # Other error, or not a symlink but doesn't exist
                                # print(f"  ℹ️ Skipping non-existent or unresolvable path: {get_relative_path(p)}", file=sys.stderr)
                                pass
        except Exception as e:
            print(f"Error during Makefile scanning: {e}", file=sys.stderr)
            sys.exit(1)
        makefiles_to_process = all_found_makefiles
        print(f"找到 {len(makefiles_to_process)} 个潜在的 Makefile 文件进行检查。")

    processed_count = 0
    total_files = len(makefiles_to_process)

    for makefile_path_obj in makefiles_to_process:
        processed_count += 1
        if total_files > 100 and (processed_count % (total_files // 20) == 0 or processed_count == 1 or processed_count == total_files) :
            print(f"PROGRESS: 已检查 {processed_count}/{total_files} 文件... (Current: {get_relative_path(makefile_path_obj)})")
        elif total_files <= 100 and (processed_count % 10 == 0 or processed_count == 1 or processed_count == total_files):
             print(f"PROGRESS: 已检查 {processed_count}/{total_files} 文件... (Current: {get_relative_path(makefile_path_obj)})")

        file_actually_modified_this_run = False
        try:
            current_target_path = makefile_path_obj

            made_version_changes = False
            made_depends_changes = False # Single flag for any depends-like change

            if args.fix_version:
                if process_makefile_version_and_release(current_target_path):
                    made_version_changes = True
            
            if args.fix_depends:
                # Process standard DEPENDS and DEPENDS_HOST
                if process_generic_depends(current_target_path, ["DEPENDS", "DEPENDS_HOST"], "STD_DEPENDS"):
                    made_depends_changes = True
                # Process LuCI specific DEPENDS and LUCI_EXTRA_DEPENDS
                if process_generic_depends(current_target_path, ["LUCI_DEPENDS", "LUCI_EXTRA_DEPENDS"], "LUCI_DEPENDS"):
                    made_depends_changes = True # If either type of depends was changed
            
            if made_version_changes or made_depends_changes:
                file_actually_modified_this_run = True

        except Exception as e_main_loop:
            print(f"  💥 处理文件 {get_relative_path(makefile_path_obj)} 时发生未预料的错误: {e_main_loop}", file=sys.stderr)

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
