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
    - 移除 PKG_VERSION 的前导 'v'。
    - 确保 PKG_RELEASE 是正整数，如果缺失则添加 '1'。
    - 处理 PKG_VERSION 包含 release 部分的情况 (如 1.2.3-5)。
    """
    relative_makefile_path = get_relative_path(makefile_path)
    print(f"  ℹ️ [VERSION/RELEASE] Processing: {relative_makefile_path}")
    try:
        if makefile_path.is_symlink():
            try:
                real_path = makefile_path.resolve(strict=True)
                if not real_path.is_file():
                    print(f"  ⚠️ [VERSION/RELEASE] Symlink {relative_makefile_path} does not point to a valid file. Skipping.", file=sys.stderr)
                    return False
                makefile_path = real_path
                relative_makefile_path = get_relative_path(makefile_path) # Update relative path if resolved
            except FileNotFoundError:
                print(f"  ⚠️ [VERSION/RELEASE] Symlink {relative_makefile_path} points to a non-existent file. Skipping.", file=sys.stderr)
                return False
            except Exception as e:
                print(f"  ⚠️ [VERSION/RELEASE] Error resolving symlink {relative_makefile_path}: {e}. Skipping.", file=sys.stderr)
                if not makefile_path.exists(): return False

        if not makefile_path.is_file():
            return False

        try:
            with open(makefile_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
        except UnicodeDecodeError as e:
            print(f"  ⚠️ [{relative_makefile_path}] [VERSION/RELEASE] Skipping due to UnicodeDecodeError: {e}. Try checking file encoding.", file=sys.stderr)
            return False
        except Exception as e:
            print(f"  ⚠️ [{relative_makefile_path}] [VERSION/RELEASE] Error reading file: {e}. Skipping.", file=sys.stderr)
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
            print(f"  ℹ️ [{relative_makefile_path}] [VERSION/RELEASE] Not a recognized OpenWrt package Makefile. Skipping version/release fixes.")
            return False

        # --- Step 1: Process PKG_VERSION first to extract base version and potential embedded release ---
        version_match = re.search(r'^(PKG_VERSION\s*:=)(.*)$', current_content, re.MULTILINE)
        base_version_val = ""
        version_embedded_release = None # Release part found inside PKG_VERSION string
        original_pkg_version_line = ""
        original_pkg_version_value_str = ""

        if version_match:
            original_pkg_version_line = version_match.group(0)
            original_pkg_version_value_raw = version_match.group(2)
            original_pkg_version_value_str = re.sub(r'\s*#.*$', '', original_pkg_version_value_raw).strip()
            
            temp_version_val = original_pkg_version_value_str
            
            # Remove 'v' prefix
            if temp_version_val.startswith('v'):
                temp_version_val = temp_version_val.lstrip('v')
                if temp_version_val != original_pkg_version_value_str:
                    print(f"    🔧 [{relative_makefile_path}] PKG_VERSION: Stripped 'v': '{original_pkg_version_value_str}' -> '{temp_version_val}'")
                    # We will reconstruct the PKG_VERSION line later with the final base_version_val

            # Try to split version into base and embedded release (e.g., "1.2.3-5")
            version_release_split_match = re.match(r'^(.*?)-(\d+)$', temp_version_val)
            if version_release_split_match:
                base_version_val = version_release_split_match.group(1)
                potential_release_part = version_release_split_match.group(2)
                if potential_release_part.isdigit() and int(potential_release_part) > 0:
                    version_embedded_release = potential_release_part
                    print(f"    ℹ️ [{relative_makefile_path}] PKG_VERSION: Found embedded release: base='{base_version_val}', embedded_release='{version_embedded_release}' from '{temp_version_val}'")
                else:
                    base_version_val = temp_version_val # No valid embedded release, use full temp_version_val
            else:
                base_version_val = temp_version_val # No embedded release pattern found

        # --- Step 2: Determine final PKG_RELEASE value ---
        release_match = re.search(r'^(PKG_RELEASE\s*:=)(.*)$', current_content, re.MULTILINE)
        final_pkg_release_val = "1" # Default
        original_pkg_release_line = ""
        original_pkg_release_value_str = ""

        if release_match:
            original_pkg_release_line = release_match.group(0)
            original_pkg_release_value_raw = release_match.group(2)
            original_pkg_release_value_str = re.sub(r'\s*#.*$', '', original_pkg_release_value_raw).strip()

            if original_pkg_release_value_str.isdigit() and int(original_pkg_release_value_str) > 0:
                final_pkg_release_val = original_pkg_release_value_str
                print(f"    ℹ️ [{relative_makefile_path}] PKG_RELEASE: Using existing valid value: '{final_pkg_release_val}'")
            else:
                print(f"    ⚠️ [{relative_makefile_path}] PKG_RELEASE: Existing value '{original_pkg_release_value_str}' is invalid.")
                if version_embedded_release:
                    final_pkg_release_val = version_embedded_release
                    print(f"      -> Using release '{version_embedded_release}' from PKG_VERSION instead.")
                else:
                    final_pkg_release_val = "1"
                    print(f"      -> Defaulting to PKG_RELEASE: '1'.")
        elif version_embedded_release: # PKG_RELEASE not defined, but found one in PKG_VERSION
            final_pkg_release_val = version_embedded_release
            print(f"    🔧 [{relative_makefile_path}] PKG_RELEASE: Using release '{version_embedded_release}' from PKG_VERSION as PKG_RELEASE was not defined.")
        else: # PKG_RELEASE not defined, no embedded release in PKG_VERSION
            print(f"    🔧 [{relative_makefile_path}] PKG_RELEASE: Not defined and no embedded release in PKG_VERSION. Defaulting to '1'.")
            final_pkg_release_val = "1"


        # --- Step 3: Apply changes to current_content ---
        # Update PKG_VERSION line to only contain base_version_val
        if version_match and base_version_val and (base_version_val != original_pkg_version_value_str):
            new_pkg_version_line = f"PKG_VERSION:={base_version_val}"
            print(f"    🔧 [{relative_makefile_path}] PKG_VERSION: Corrected to base version: '{original_pkg_version_value_str}' -> '{base_version_val}'")
            current_content = current_content.replace(original_pkg_version_line, new_pkg_version_line, 1)
            modified_in_file = True
        elif not version_match and base_version_val: # Should not happen if PKG_VERSION is required for a package
             print(f"    ⚠️ [{relative_makefile_path}] PKG_VERSION line not found, but base_version_val ('{base_version_val}') was derived. This is unusual.")


        # Update or add PKG_RELEASE line
        if release_match: # PKG_RELEASE was defined
            if final_pkg_release_val != original_pkg_release_value_str:
                new_pkg_release_line = f"PKG_RELEASE:={final_pkg_release_val}"
                print(f"    🔧 [{relative_makefile_path}] PKG_RELEASE: Updated value: '{original_pkg_release_value_str}' -> '{final_pkg_release_val}'")
                current_content = current_content.replace(original_pkg_release_line, new_pkg_release_line, 1)
                modified_in_file = True
        elif version_present_in_content: # PKG_RELEASE was not defined, add it after PKG_VERSION
            new_pkg_release_line = f"PKG_RELEASE:={final_pkg_release_val}"
            # Find the (potentially modified) PKG_VERSION line to insert after
            current_pkg_version_line_match_for_insert = re.search(r'^(PKG_VERSION\s*:=.*)$', current_content, re.MULTILINE)
            if current_pkg_version_line_match_for_insert:
                line_to_insert_after = current_pkg_version_line_match_for_insert.group(1)
                print(f"    🔧 [{relative_makefile_path}] PKG_RELEASE: Added new line: '{new_pkg_release_line}'")
                current_content = current_content.replace(line_to_insert_after, f"{line_to_insert_after}\n{new_pkg_release_line}", 1)
                modified_in_file = True
            else:
                print(f"    ⚠️ [{relative_makefile_path}] Could not find PKG_VERSION line to insert new PKG_RELEASE after. PKG_RELEASE not added.")


        if modified_in_file:
            if current_content != original_content:
                print(f"  💾 [{relative_makefile_path}] [VERSION/RELEASE] Saving changes.")
                with open(makefile_path, 'w', encoding='utf-8') as f:
                    f.write(current_content)
                return True
            else:
                print(f"  ℹ️ [{relative_makefile_path}] [VERSION/RELEASE] Modifications attempted but result is identical to original. No save needed.")
        else:
            print(f"  ℹ️ [{relative_makefile_path}] [VERSION/RELEASE] No version/release changes needed.")
        return False

    except Exception as e:
        print(f"  ⚠️ [VERSION/RELEASE] Processing {relative_makefile_path} failed: {e}", file=sys.stderr)
        return False

def process_makefile_depends(makefile_path: Path):
    """
    修复单个 Makefile 中的 DEPENDS 字段。
    - 移除版本约束 (如 >=, <=, =)。
    - 移除重复项 (对于非复杂 Make 语法)。
    - 优先保留 '@' 前缀的依赖项。
    """
    relative_makefile_path = get_relative_path(makefile_path)
    print(f"  ℹ️ [DEPENDS] Processing: {relative_makefile_path}")
    try:
        if makefile_path.is_symlink():
            try:
                real_path = makefile_path.resolve(strict=True)
                if not real_path.is_file():
                    print(f"  ⚠️ [DEPENDS] Symlink {relative_makefile_path} does not point to a valid file. Skipping.", file=sys.stderr)
                    return False
                makefile_path = real_path
                relative_makefile_path = get_relative_path(makefile_path) # Update relative path
            except FileNotFoundError:
                print(f"  ⚠️ [DEPENDS] Symlink {relative_makefile_path} points to a non-existent file. Skipping.", file=sys.stderr)
                return False
            except Exception as e:
                print(f"  ⚠️ [DEPENDS] Error resolving symlink {relative_makefile_path}: {e}. Skipping.", file=sys.stderr)
                if not makefile_path.exists(): return False

        if not makefile_path.is_file():
            return False

        try:
            with open(makefile_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
        except UnicodeDecodeError as e:
            print(f"  ⚠️ [{relative_makefile_path}] [DEPENDS] Skipping due to UnicodeDecodeError: {e}. Check file encoding.", file=sys.stderr)
            return False
        except Exception as e:
            print(f"  ⚠️ [{relative_makefile_path}] [DEPENDS] Error reading file: {e}. Skipping.", file=sys.stderr)
            return False

        original_content = content

        is_package_makefile = ('define Package/' in content and 'endef' in content) or \
                              ('include $(TOPDIR)/rules.mk' in content or \
                               'include $(INCLUDE_DIR)/package.mk' in content or \
                               'include ../../buildinfo.mk' in content or \
                               '$(eval $(call BuildPackage))' in content)
        if not is_package_makefile:
            print(f"  ℹ️ [{relative_makefile_path}] [DEPENDS] Not a recognized OpenWrt package Makefile. Skipping DEPENDS fixes.")
            return False

        depends_regex = r'^([ \t]*(?:DEPENDS|DEPENDS_HOST)\s*[:+]?=\s*)((?:.*?\\\n)*.*)$'
        file_level_modified_flag = False
        new_content = content
        offset_adjustment = 0

        matches = list(re.finditer(depends_regex, content, re.MULTILINE | re.IGNORECASE))
        if not matches:
            print(f"  ℹ️ [{relative_makefile_path}] [DEPENDS] No DEPENDS lines found.")
            return False
        
        print(f"    Found {len(matches)} DEPENDS/DEPENDS_HOST block(s) in {relative_makefile_path}.")

        for i, match_obj in enumerate(matches):
            current_match_start_offset = match_obj.start() + offset_adjustment
            current_match_end_offset = match_obj.end() + offset_adjustment
            original_depends_line_block = match_obj.group(0)
            
            print(f"    🔍 [{relative_makefile_path}] [DEPENDS Block {i+1}] Original: {original_depends_line_block.strip()}")

            prefix_group = match_obj.group(1)
            depends_value_raw = match_obj.group(2)
            
            depends_value_no_line_breaks = depends_value_raw.replace('\\\n', ' ')
            depends_value_cleaned_comments = re.sub(r'\s*#.*', '', depends_value_no_line_breaks, flags=re.MULTILINE).strip()
            original_depends_for_log = depends_value_cleaned_comments

            is_line_structurally_complex = is_structurally_complex_item(depends_value_cleaned_comments)
            if is_line_structurally_complex:
                print(f"      ⚠️ [{relative_makefile_path}] [DEPENDS Block {i+1}] Contains complex Makefile syntax. Version/duplicate cleaning will be conservative.")


            depends_items_list_raw = re.split(r'\s+', depends_value_cleaned_comments)
            processed_dependency_items = []
            items_were_modified_this_block = False

            for item_str_raw in depends_items_list_raw:
                item_str = item_str_raw.strip()
                if not item_str:
                    continue

                original_item_for_comparison = item_str
                current_processed_item = item_str

                item_prefix_char = ""
                item_name_part = item_str
                if item_str.startswith('+') or item_str.startswith('@'):
                    item_prefix_char = item_str[0]
                    item_name_part = item_str[1:]

                name_parts = re.split(r'[>=<~]', item_name_part, 1)
                cleaned_name_candidate = name_parts[0].strip()

                if cleaned_name_candidate:
                    if not is_structurally_complex_item(item_name_part) and \
                       not re.match(r'^[a-zA-Z0-9._~+-]+$', cleaned_name_candidate):
                        print(f"        ⚠️ [{relative_makefile_path}] [DEPENDS Item] Invalid simple name '{cleaned_name_candidate}' from '{item_str}'. Reverting to '{item_name_part}'.")
                        cleaned_name_candidate = item_name_part
                
                if cleaned_name_candidate:
                    current_processed_item = f"{item_prefix_char}{cleaned_name_candidate}"
                elif item_prefix_char:
                    current_processed_item = item_prefix_char
                else:
                    current_processed_item = ""

                if current_processed_item != original_item_for_comparison:
                    items_were_modified_this_block = True
                    if original_item_for_comparison:
                         print(f"        🔧 [{relative_makefile_path}] [DEPENDS Item] Version constraint: '{original_item_for_comparison}' -> '{current_processed_item or '(removed)'}'")

                if current_processed_item:
                    processed_dependency_items.append(current_processed_item)
                elif original_item_for_comparison:
                    items_were_modified_this_block = True

            final_dependency_string = ""
            if is_line_structurally_complex:
                final_dependency_string = ' '.join(processed_dependency_items)
                if final_dependency_string != original_depends_for_log:
                     items_were_modified_this_block = True
                # else: no change if string is same, items_were_modified_this_block retains its value
            else: # Not complex, apply de-duplication
                seen_names = {}
                unique_deps_ordered = []
                temp_final_items = {}
                for item in processed_dependency_items:
                    dep_prefix = ""
                    dep_name = item
                    if item.startswith('+') or item.startswith('@'):
                        dep_prefix = item[0]
                        dep_name = item[1:]
                    
                    if not dep_name:
                        if dep_prefix and dep_prefix not in temp_final_items:
                            temp_final_items[dep_prefix] = dep_prefix
                        continue

                    if dep_name not in temp_final_items:
                        temp_final_items[dep_name] = item
                    else:
                        existing_item = temp_final_items[dep_name]
                        existing_prefix = ""
                        if existing_item.startswith('+') or existing_item.startswith('@'):
                            existing_prefix = existing_item[0]
                        
                        if dep_prefix == '@':
                            temp_final_items[dep_name] = item
                        elif dep_prefix == '+' and existing_prefix == '':
                            temp_final_items[dep_name] = item
                
                added_names_to_final_list = set()
                for item in processed_dependency_items:
                    dep_prefix = ""
                    dep_name = item
                    if item.startswith('+') or item.startswith('@'):
                        dep_prefix = item[0]
                        dep_name = item[1:]
                    key_for_lookup = dep_name if dep_name else dep_prefix
                    if key_for_lookup and key_for_lookup not in added_names_to_final_list:
                        if key_for_lookup in temp_final_items:
                            unique_deps_ordered.append(temp_final_items[key_for_lookup])
                            added_names_to_final_list.add(key_for_lookup)

                final_dependency_string = ' '.join(unique_deps_ordered)
                if final_dependency_string != original_depends_for_log:
                    items_were_modified_this_block = True
                    print(f"        🔧 [{relative_makefile_path}] [DEPENDS Block {i+1}] De-duplicated/Reordered: '{original_depends_for_log}' -> '{final_dependency_string}'")
                elif not items_were_modified_this_block and len(processed_dependency_items) != len(unique_deps_ordered):
                    items_were_modified_this_block = True
                    print(f"        🔧 [{relative_makefile_path}] [DEPENDS Block {i+1}] De-duplicated (only): '{original_depends_for_log}' -> '{final_dependency_string}'")


            if items_were_modified_this_block:
                new_depends_line_content = f"{prefix_group}{final_dependency_string}"
                print(f"    ✅ [{relative_makefile_path}] [DEPENDS Block {i+1}] Finalized: {new_depends_line_content.strip()}")
                
                block_in_current_new_content = new_content[current_match_start_offset : current_match_end_offset]
                if block_in_current_new_content == original_depends_line_block:
                    new_content = new_content[:current_match_start_offset] + new_depends_line_content + new_content[current_match_end_offset:]
                    offset_adjustment += len(new_depends_line_content) - len(original_depends_line_block)
                    file_level_modified_flag = True
                else:
                    print(f"      ❌ [{relative_makefile_path}] [DEPENDS Block {i+1}] Content offset mismatch. Trying string replacement for original block.")
                    try:
                        # This is a simplified replacement. If original_depends_line_block is not unique, this could be an issue.
                        # However, for sequential processing of matches, it should target the current one if new_content is updated carefully.
                        # A count=1 ensures only the first occurrence (hopefully the current one) is replaced.
                        temp_new_content, num_replacements = re.subn(re.escape(original_depends_line_block), new_depends_line_content, new_content, count=1)
                        if num_replacements > 0:
                            new_content = temp_new_content
                            offset_adjustment = len(new_content) - len(original_content) # Recalculate full offset
                            file_level_modified_flag = True
                            print(f"        ✅ [{relative_makefile_path}] [DEPENDS Block {i+1}] Fallback string replacement successful.")
                        else:
                             print(f"        ❌ [{relative_makefile_path}] [DEPENDS Block {i+1}] Fallback string replacement failed: Original block not found. Skipping this modification.")
                    except Exception as e_replace_fallback:
                        print(f"        ❌ [{relative_makefile_path}] [DEPENDS Block {i+1}] Error during fallback replacement: {e_replace_fallback}. Skipping this modification.")
            else:
                print(f"    ℹ️ [{relative_makefile_path}] [DEPENDS Block {i+1}] No changes needed for this block.")


        if file_level_modified_flag and new_content != original_content:
            print(f"  💾 [{relative_makefile_path}] [DEPENDS] Saving changes.")
            with open(makefile_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            return True
        elif file_level_modified_flag and new_content == original_content:
             print(f"  ℹ️ [{relative_makefile_path}] [DEPENDS] Modifications attempted but result is identical to original. No save needed.")
        else:
            print(f"  ℹ️ [{relative_makefile_path}] [DEPENDS] No changes made to any DEPENDS blocks.")
        return False # Return True only if content was actually changed and saved

    except FileNotFoundError:
        print(f"  ⚠️ [DEPENDS] File not found: {relative_makefile_path}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"  ⚠️ [DEPENDS] Processing {relative_makefile_path} failed: {e}", file=sys.stderr)
        return False
def process_luci_depends(makefile_path: Path):
    """
    修复单个 Makefile 中的 LUCI_DEPENDS 和 LUCI_EXTRA_DEPENDS 字段。
    - 从两者中提取依赖项。
    - 移除版本约束和括号。
    - 合并、去重，并用干净的列表重写 LUCI_DEPENDS。
    - 如果 LUCI_EXTRA_DEPENDS 处理后为空，则注释掉它。
    """
    relative_makefile_path = get_relative_path(makefile_path)
    print(f"  ℹ️ [LUCI_DEPENDS] Processing: {relative_makefile_path}")
    try:
        if makefile_path.is_symlink():
            try:
                real_path = makefile_path.resolve(strict=True)
                if not real_path.is_file():
                    print(f"  ⚠️ [LUCI_DEPENDS] Symlink {relative_makefile_path} does not point to a valid file. Skipping.", file=sys.stderr)
                    return False
                makefile_path = real_path
                relative_makefile_path = get_relative_path(makefile_path)
            except FileNotFoundError:
                print(f"  ⚠️ [LUCI_DEPENDS] Symlink {relative_makefile_path} points to a non-existent file. Skipping.", file=sys.stderr)
                return False
            except Exception as e:
                print(f"  ⚠️ [LUCI_DEPENDS] Error resolving symlink {relative_makefile_path}: {e}. Skipping.", file=sys.stderr)
                if not makefile_path.exists(): return False

        if not makefile_path.is_file():
            return False

        try:
            with open(makefile_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
        except UnicodeDecodeError as e:
            print(f"  ⚠️ [{relative_makefile_path}] [LUCI_DEPENDS] Skipping due to UnicodeDecodeError: {e}. Check file encoding.", file=sys.stderr)
            return False
        except Exception as e:
            print(f"  ⚠️ [{relative_makefile_path}] [LUCI_DEPENDS] Error reading file: {e}. Skipping.", file=sys.stderr)
            return False

        original_content = content
        current_content = content # Start with original content for modifications
        file_modified_flag = False

        # Check if it's a LuCI package Makefile (heuristic)
        is_luci_makefile = ('include $(TOPDIR)/feeds/luci/luci.mk' in content or \
                            'LUCI_TITLE:=' in content)
        if not is_luci_makefile:
            print(f"  ℹ️ [{relative_makefile_path}] [LUCI_DEPENDS] Not a recognized LuCI package Makefile. Skipping LuCI depends fixes.")
            return False

        all_luci_deps_raw = []
        luci_depends_match = re.search(r'^(LUCI_DEPENDS\s*[:+]?=\s*)((?:.*?\\\n)*.*)$', current_content, re.MULTILINE | re.IGNORECASE)
        luci_extra_depends_match = re.search(r'^(LUCI_EXTRA_DEPENDS\s*[:+]?=\s*)((?:.*?\\\n)*.*)$', current_content, re.MULTILINE | re.IGNORECASE)

        original_luci_depends_line = ""
        original_luci_extra_depends_line = ""

        if luci_depends_match:
            original_luci_depends_line = luci_depends_match.group(0)
            depends_value_raw = luci_depends_match.group(2).replace('\\\n', ' ')
            depends_value_cleaned = re.sub(r'\s*#.*', '', depends_value_raw, flags=re.MULTILINE).strip()
            if depends_value_cleaned:
                all_luci_deps_raw.extend(re.split(r'\s+', depends_value_cleaned))
            print(f"    🔍 [{relative_makefile_path}] Found LUCI_DEPENDS: {depends_value_cleaned}")


        if luci_extra_depends_match:
            original_luci_extra_depends_line = luci_extra_depends_match.group(0)
            extra_depends_value_raw = luci_extra_depends_match.group(2).replace('\\\n', ' ')
            extra_depends_value_cleaned = re.sub(r'\s*#.*', '', extra_depends_value_raw, flags=re.MULTILINE).strip()
            if extra_depends_value_cleaned:
                all_luci_deps_raw.extend(re.split(r'\s+', extra_depends_value_cleaned))
            print(f"    🔍 [{relative_makefile_path}] Found LUCI_EXTRA_DEPENDS: {extra_depends_value_cleaned}")

        if not all_luci_deps_raw:
            print(f"  ℹ️ [{relative_makefile_path}] [LUCI_DEPENDS] No LUCI_DEPENDS or LUCI_EXTRA_DEPENDS found or they are empty.")
            return False

        processed_luci_deps = []
        items_were_modified_in_luci_processing = False

        for item_str_raw in all_luci_deps_raw:
            item_str = item_str_raw.strip()
            if not item_str:
                continue

            original_item_for_comparison = item_str
            
            # Remove version constraints like (>=1.0), (=1.2), etc. and surrounding parentheses
            # This regex tries to find a package name optionally followed by space and (...)
            # It's a bit greedy, assumes simple structure.
            item_cleaned = re.sub(r'\s*\([<>=~].*?\)', '', item_str).strip()
            item_cleaned = item_cleaned.replace('(', '').replace(')', '').strip() # Remove stray parentheses

            if item_cleaned != original_item_for_comparison:
                items_were_modified_in_luci_processing = True
                print(f"        🔧 [{relative_makefile_path}] [LuCI Dep Item] Cleaned: '{original_item_for_comparison}' -> '{item_cleaned or '(removed)'}'")
            
            if item_cleaned: # Add if not empty after cleaning
                 # Check for structural complexity after cleaning version constraints
                if is_structurally_complex_item(item_cleaned):
                    print(f"          ⚠️ [{relative_makefile_path}] [LuCI Dep Item] Cleaned item '{item_cleaned}' still contains Makefile syntax. Preserving as is.")
                    processed_luci_deps.append(item_cleaned) # Add as is if complex
                elif not re.match(r'^[+@a-zA-Z0-9._~-]+$', item_cleaned): # Allow +, @, and typical package name chars
                    print(f"          ⚠️ [{relative_makefile_path}] [LuCI Dep Item] Cleaned item '{item_cleaned}' contains invalid characters. Reverting to '{original_item_for_comparison}'.")
                    processed_luci_deps.append(original_item_for_comparison) # Revert if invalid simple name
                else:
                    processed_luci_deps.append(item_cleaned)
            elif original_item_for_comparison: # Log if a non-empty item was removed
                items_were_modified_in_luci_processing = True


        # De-duplicate, preferring items with prefixes (@ > + > none)
        # This logic is similar to the one in process_makefile_depends
        temp_final_items = {}
        for item in processed_luci_deps:
            dep_prefix = ""
            dep_name = item
            if item.startswith('+') or item.startswith('@'):
                dep_prefix = item[0]
                dep_name = item[1:]
            
            if not dep_name: # Handle standalone prefix like "+" or "@"
                if dep_prefix and dep_prefix not in temp_final_items:
                    temp_final_items[dep_prefix] = dep_prefix
                continue

            if dep_name not in temp_final_items:
                temp_final_items[dep_name] = item
            else:
                existing_item = temp_final_items[dep_name]
                existing_prefix = ""
                if existing_item.startswith('+') or existing_item.startswith('@'):
                    existing_prefix = existing_item[0]
                
                if dep_prefix == '@':
                    temp_final_items[dep_name] = item
                elif dep_prefix == '+' and existing_prefix == '':
                    temp_final_items[dep_name] = item
        
        unique_luci_deps_ordered = []
        added_names_to_final_list = set()
        for item in processed_luci_deps: # Iterate original processed items for order
            dep_prefix = ""
            dep_name = item
            if item.startswith('+') or item.startswith('@'):
                dep_prefix = item[0]
                dep_name = item[1:]
            key_for_lookup = dep_name if dep_name else dep_prefix
            if key_for_lookup and key_for_lookup not in added_names_to_final_list:
                if key_for_lookup in temp_final_items:
                    unique_luci_deps_ordered.append(temp_final_items[key_for_lookup])
                    added_names_to_final_list.add(key_for_lookup)
        
        final_luci_depends_string = ' '.join(unique_luci_deps_ordered)
        
        # Construct the original full string of all deps for comparison
        original_all_deps_string_for_comparison_list = []
        if luci_depends_match:
            original_all_deps_string_for_comparison_list.append(re.sub(r'\s*#.*', '', luci_depends_match.group(2).replace('\\\n', ' ')).strip())
        if luci_extra_depends_match:
             original_all_deps_string_for_comparison_list.append(re.sub(r'\s*#.*', '', luci_extra_depends_match.group(2).replace('\\\n', ' ')).strip())
        original_combined_deps_str = ' '.join(filter(None, original_all_deps_string_for_comparison_list))


        if final_luci_depends_string != original_combined_deps_str or items_were_modified_in_luci_processing:
            file_modified_flag = True
            print(f"    ✅ [{relative_makefile_path}] [LUCI_DEPENDS] Consolidated and cleaned. Original combined: '{original_combined_deps_str}', New: '{final_luci_depends_string}'")

            # Replace or add LUCI_DEPENDS
            new_luci_depends_line = f"LUCI_DEPENDS:={final_luci_depends_string}"
            if luci_depends_match: # LUCI_DEPENDS existed
                current_content = current_content.replace(original_luci_depends_line, new_luci_depends_line, 1)
            else: # LUCI_DEPENDS did not exist, try to add it (e.g., after LUCI_TITLE)
                luci_title_match = re.search(r'^(LUCI_TITLE\s*:=.*)$', current_content, re.MULTILINE)
                if luci_title_match:
                    title_line = luci_title_match.group(1)
                    current_content = current_content.replace(title_line, f"{title_line}\n{new_luci_depends_line}", 1)
                    print(f"      🔧 [{relative_makefile_path}] Added new LUCI_DEPENDS line.")
                else: # Fallback: add at the top after include rules.mk
                    rules_mk_match = re.search(r'^(include \$\(TOPDIR\)/rules\.mk.*)$', current_content, re.MULTILINE)
                    if rules_mk_match:
                        rules_line = rules_mk_match.group(1)
                        current_content = current_content.replace(rules_line, f"{rules_line}\n\n{new_luci_depends_line}", 1)
                        print(f"      🔧 [{relative_makefile_path}] Added new LUCI_DEPENDS line (after rules.mk).")
                    else:
                        print(f"      ⚠️ [{relative_makefile_path}] Could not determine where to add new LUCI_DEPENDS line.")
                        file_modified_flag = False # Can't make this change

            # Comment out LUCI_EXTRA_DEPENDS if it existed
            if luci_extra_depends_match and original_luci_extra_depends_line.strip():
                commented_extra_depends_line = f"#{original_luci_extra_depends_line.lstrip()}" # Preserve indentation
                current_content = current_content.replace(original_luci_extra_depends_line, commented_extra_depends_line, 1)
                print(f"      🔧 [{relative_makefile_path}] Commented out original LUCI_EXTRA_DEPENDS.")
        else:
            print(f"  ℹ️ [{relative_makefile_path}] [LUCI_DEPENDS] No changes needed for LuCI dependencies.")


        if file_modified_flag and current_content != original_content:
            print(f"  💾 [{relative_makefile_path}] [LUCI_DEPENDS] Saving changes.")
            with open(makefile_path, 'w', encoding='utf-8') as f:
                f.write(current_content)
            return True
        elif file_modified_flag and current_content == original_content:
            print(f"  ℹ️ [{relative_makefile_path}] [LUCI_DEPENDS] Modifications attempted but result is identical to original. No save needed.")
        return False

    except Exception as e:
        print(f"  ⚠️ [LUCI_DEPENDS] Processing {relative_makefile_path} failed: {e}", file=sys.stderr)
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
            for pattern in ['Makefile', 'makefile']:
                for p in base_path.rglob(pattern):
                    if not any(ignored_dir in p.parts for ignored_dir in ignore_dirs):
                        resolved_p = p.resolve()
                        if resolved_p not in [m.resolve() for m in all_found_makefiles]:
                             all_found_makefiles.append(p)
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
            current_target_path = makefile_path_obj # process_* functions handle symlinks now

            made_version_changes = False
            made_std_depends_changes = False
            made_luci_depends_changes = False

            if args.fix_version:
                if process_makefile_version_and_release(current_target_path):
                    made_version_changes = True
            
            if args.fix_depends: # This flag now covers both standard and LuCI depends
                # Process standard DEPENDS first
                if process_makefile_depends(current_target_path):
                    made_std_depends_changes = True
                # Then process LuCI specific depends
                if process_luci_depends(current_target_path):
                    made_luci_depends_changes = True
            
            if made_version_changes or made_std_depends_changes or made_luci_depends_changes:
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
