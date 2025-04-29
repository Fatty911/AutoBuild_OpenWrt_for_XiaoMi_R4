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
import tempfile

# --- Global variable for log content ---
log_content_global = ""

def get_relative_path(path):
    """获取相对路径，优先相对于当前工作目录"""
    current_pwd = os.getcwd()
    try:
        abs_path = Path(path).resolve()
        if abs_path.is_relative_to(current_pwd):
            return str(abs_path.relative_to(current_pwd))
        else:
            return str(abs_path)
    except (ValueError, OSError, Exception):
        return str(path)

# --- Error Signature Detection ---
def get_error_signature(log_content):
    """Detects specific error signatures from the build log."""
    if not log_content: return "no_log_content"

    # --- Batman-adv multicast.c implicit declaration error ---
    batman_adv_error_match = re.search(
        r"batman-adv/multicast\.c.*error: implicit declaration of function 'br_multicast_has_router_adjacent'.*?did you mean 'br_multicast_has_querier_adjacent'.*?make\[\d+\]: \*\*\* .*?batman-adv.*? Error \d+",
        log_content, re.DOTALL | re.IGNORECASE
    )
    if batman_adv_error_match:
        return "batman_adv_multicast_implicit_decl"

    # --- Batman-adv patch failed error (specifically 0001 if we modify it) ---
    patch_failed_match = re.search(
        r"Applying.*?patches/0001-Revert-batman-adv-Migrate-to-linux-container_of\.h\.patch.*?FAILED.*?Patch failed!",
        log_content, re.DOTALL | re.IGNORECASE
    )
    if patch_failed_match:
        return "batman_adv_patch_0001_failed" # Signature if our modified patch fails

    # --- Generic Error (fallback) ---
    generic_error_match = re.search(r'(error:|failed|fatal error:|collect2: error: ld returned 1 exit status)', log_content, re.IGNORECASE)
    if generic_error_match:
        pkg_fail_match = re.search(r"ERROR: package/(?:feeds/[^/]+/|pkgs/|libs/|utils/|network/)?([^/]+) failed to build", log_content)
        pkg_name = pkg_fail_match.group(1) if pkg_fail_match else "unknown_pkg"
        error_keyword = generic_error_match.group(1).lower().split(':')[0].replace(' ', '_')
        context_line = ""
        for line in reversed(log_content.splitlines()):
             if generic_error_match.group(1).lower() in line.lower():
                 context_line = re.sub(r'\x1b\[[0-9;]*[mK]', '', line).strip()
                 context_line = re.sub(r'[^a-zA-Z0-9\s\._\-\+=:/]', '', context_line)[:80]
                 break
        return f"generic_error:{error_keyword}:{pkg_name}:{context_line}"

    return "unknown_error"

# --- Fix Function ---
def fix_batman_adv_modify_patch_0001():
    """
    Fixes the implicit declaration error by modifying the existing patch
    '0001-Revert-batman-adv-Migrate-to-linux-container_of.h.patch'
    to include the function name change for multicast.c.
    """
    print("🔧 检测到 batman-adv multicast.c 错误，尝试修改现有补丁 0001...")
    patch_modified = False
    patch_dir = Path("feeds/routing/batman-adv/patches")
    patch_filename = "0001-Revert-batman-adv-Migrate-to-linux-container_of.h.patch"
    patch_path = patch_dir / patch_filename
    patch_path_rel = get_relative_path(str(patch_path))

    old_func = "br_multicast_has_router_adjacent"
    new_func = "br_multicast_has_querier_adjacent"
    target_file_in_patch = "net/batman-adv/multicast.c"

    if not patch_path.exists():
        print(f"❌ 错误：找不到目标补丁文件 '{patch_path_rel}' 进行修改。")
        return False

    try:
        print(f"读取补丁文件: {patch_path_rel}")
        with open(patch_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        new_lines = []
        in_multicast_hunk = False
        found_line_to_modify = False
        already_modified = False

        for line in lines:
            current_line = line # Keep original for appending if no change

            # Detect start of hunk for the target file
            if line.startswith(f"--- a/{target_file_in_patch}") or line.startswith(f"+++ b/{target_file_in_patch}"):
                in_multicast_hunk = True
            # Detect end of hunk (start of a new file's hunk)
            elif line.startswith("--- a/") and in_multicast_hunk:
                in_multicast_hunk = False
            # Detect end of hunk (end of patch file) - less reliable but fallback
            # elif not line.strip() and in_multicast_hunk: # Approximation
            #     in_multicast_hunk = False

            if in_multicast_hunk:
                # Look for the specific line within the hunk (must start with ' ' or '-')
                # The line in the patch might start with '-' if it's being removed, or ' ' if context
                # We expect it to be context (' ') or possibly added ('+') in the original patch 0001
                line_content = line.strip()
                if old_func in line_content and (line.startswith(' ') or line.startswith('+') or line.startswith('-')):
                    print(f"  找到包含 '{old_func}' 的行: {line.rstrip()}")
                    # Replace the function name within this line
                    modified_line = line.replace(old_func, new_func)
                    print(f"  修改为: {modified_line.rstrip()}")
                    new_lines.append(modified_line)
                    found_line_to_modify = True
                    patch_modified = True
                    continue # Go to next line after appending modified one
                elif new_func in line_content and (line.startswith(' ') or line.startswith('+') or line.startswith('-')):
                     # If the new function is already there, assume it's fixed
                     already_modified = True
                     print(f"  发现函数 '{new_func}' 已存在于补丁中: {line.rstrip()}")


            # Append the original or unmodified line if no change was made above
            new_lines.append(current_line)
            # Reset in_multicast_hunk if we reach the end of the file within the hunk
            # This check might be redundant if the file ends correctly after the hunk.
            # if line is lines[-1] and in_multicast_hunk:
            #      in_multicast_hunk = False


        if already_modified:
            print(f"ℹ️ 补丁 '{patch_path_rel}' 似乎已包含所需更改。")
            patch_modified = False # Don't rewrite if already correct
        elif not found_line_to_modify:
            print(f"❌ 错误：未能在补丁 '{patch_path_rel}' 的 {target_file_in_patch} 部分找到包含 '{old_func}' 的行进行修改。")
            # This implies the structure of patch 0001 changed or doesn't contain the expected context.
            # Trying to generate a new patch might be the only option left, but let's fail for now.
            return False
        elif patch_modified:
            print(f"准备写回修改后的补丁: {patch_path_rel}")
            # Create a backup of the original patch
            backup_patch_path = patch_path.with_suffix(patch_path.suffix + ".bak")
            try:
                shutil.copy2(patch_path, backup_patch_path)
                print(f"创建原始补丁备份: {get_relative_path(str(backup_patch_path))}")
            except Exception as backup_e:
                print(f"⚠️ 创建补丁备份失败: {backup_e}")

            # Write the modified content
            with open(patch_path, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
            print(f"✅ 成功修改补丁文件 {patch_path_rel}。")

    except Exception as e:
        print(f"❌ 修改补丁文件 {patch_path_rel} 时出错: {e}")
        return False

    # Always clean the package after detecting the error to force re-patching
    print("🧹 清理 batman-adv 包以应用修改后的补丁...")
    clean_package()

    # Return True because we've identified the error and taken the corrective action
    return True

def clean_package():
    """Runs make clean for the batman-adv package."""
    clean_cmd = ["make", "package/feeds/routing/batman-adv/clean", "V=s"]
    try:
        result = subprocess.run(clean_cmd, check=False, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(f"⚠️ batman-adv 清理可能失败 (返回码 {result.returncode}):\n{result.stderr[-500:]}")
        else:
            print("✅ batman-adv 清理完成。")
    except subprocess.TimeoutExpired:
         print("⚠️ 清理 batman-adv 时超时。")
    except Exception as e:
        print(f"⚠️ 执行清理命令时出错: {e}")

def handle_failed_patch_0001():
    """Handles the case where our *modified* patch 0001 failed to apply."""
    print("❌ 检测到修改后的补丁 0001 应用失败。")
    patch_path = Path("feeds/routing/batman-adv/patches/0001-Revert-batman-adv-Migrate-to-linux-container_of.h.patch")
    backup_patch_path = patch_path.with_suffix(patch_path.suffix + ".bak")

    if backup_patch_path.exists():
        print(f"尝试从备份恢复原始补丁 0001...")
        try:
            shutil.move(str(backup_patch_path), patch_path)
            print("✅ 已恢复原始补丁 0001。")
            # Clean again after restoring
            clean_package()
            return True # Indicate action taken
        except Exception as e:
            print(f"❌ 恢复原始补丁 0001 失败: {e}")
            # If restore fails, maybe delete the modified one? Risky.
            return False
    else:
        print("⚠️ 未找到补丁 0001 的备份文件 (.bak)。无法自动恢复。")
        return False


# --- Map Signatures to Fix Functions ---
FIX_FUNCTIONS = {
    "batman_adv_multicast_implicit_decl": fix_batman_adv_modify_patch_0001,
    "batman_adv_patch_0001_failed": handle_failed_patch_0001, # Handle if our modified patch fails
    # Add other error signatures and their fix functions here if needed
}

# --- Main Logic (Mostly unchanged from previous version) ---
def main():
    parser = argparse.ArgumentParser(description='OpenWrt Batman-adv 编译修复脚本')
    parser.add_argument('make_command', help='原始编译命令，例如 "make package/feeds/routing/batman-adv/compile V=s"')
    parser.add_argument('log_file', help='日志文件基础名 (不含 .run.N.log)')
    parser.add_argument('--max-retry', type=int, default=3, help='最大重试次数')
    parser.add_argument('--jobs', type=int, default=1, help='并行任务数 (通常为 1 用于包编译)')
    args = parser.parse_args()

    base_cmd = re.sub(r'\s-j\s*\d+', '', args.make_command).strip()
    jobs = args.jobs if args.jobs > 0 else 1

    retry = 1
    last_error_signature = None
    fix_attempt_made_in_last_cycle = False # Track if fix was run

    while retry <= args.max_retry:
        current_run_log = f"{args.log_file}.run.{retry}.log"
        cmd = f"{base_cmd} -j{jobs}"

        print(f"\n--- 尝试 {retry}/{args.max_retry} ---")
        print(f"运行命令: {cmd}")
        print(f"日志文件: {current_run_log}")

        status = -1
        process = None
        try:
            process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, encoding='utf-8', errors='replace', bufsize=1)

            with open(current_run_log, 'w', encoding='utf-8', errors='replace') as f:
                for line in iter(process.stdout.readline, ''):
                    sys.stdout.write(line)
                    f.write(line)
            process.stdout.close()
            status = process.wait()

        except KeyboardInterrupt:
             print("\n🛑 检测到中断信号，正在终止...")
             if process and process.poll() is None:
                 process.terminate()
                 try: process.wait(timeout=5)
                 except subprocess.TimeoutExpired: process.kill()
             sys.exit(130)
        except Exception as e:
            print(f"\n❌ 执行编译命令时发生异常: {e}")
            try:
                with open(current_run_log, 'a', encoding='utf-8', errors='replace') as f:
                    f.write(f"\n\n*** SCRIPT ERROR DURING EXECUTION ***\n{e}\n")
            except Exception: pass
            status = 1

        # --- Process Results ---
        if status == 0:
            print("\n✅ 编译成功！")
            return 0

        print(f"\n❌ 编译失败 (返回码: {status})")

        # Read log content for error analysis
        log_content_global = ""
        try:
            if process: process.wait()
            time.sleep(0.2)
            with open(current_run_log, 'r', encoding='utf-8', errors='replace') as f:
                log_content_global = f.read()
        except FileNotFoundError:
             print(f"❌ 无法读取日志文件: {current_run_log}")
             current_error_signature = "no_log_content_error"
        except Exception as e:
             print(f"❌ 读取日志文件时发生错误: {e}")
             current_error_signature = "log_read_error"
        else:
             current_error_signature = get_error_signature(log_content_global)

        print(f"检测到的错误签名: {current_error_signature}")

        # --- Consecutive Error Check ---
        if fix_attempt_made_in_last_cycle and current_error_signature == last_error_signature:
             if current_error_signature == "batman_adv_multicast_implicit_decl":
                 print(f"错误 '{current_error_signature}' 在尝试修复后仍然立即出现，停止重试。")
                 break
             elif current_error_signature == "batman_adv_patch_0001_failed":
                  print(f"补丁 0001 应用在尝试修复后仍然失败，停止重试。")
                  break
        elif fix_attempt_made_in_last_cycle and current_error_signature != last_error_signature:
             print(f"出现新的错误 '{current_error_signature}' 在尝试修复 '{last_error_signature}' 后，停止重试。")
             break

        last_error_signature = current_error_signature
        fix_attempt_made_in_last_cycle = False # Reset flag

        # --- Attempt Fixes ---
        if current_error_signature in FIX_FUNCTIONS:
            fix_func = FIX_FUNCTIONS[current_error_signature]
            if fix_func():
                 fix_attempt_made_in_last_cycle = True
            else:
                 print(f"修复函数针对 '{current_error_signature}' 执行但未成功完成，停止重试。")
                 break
        # ... (rest of the error handling remains the same) ...
        elif current_error_signature == "unknown_error":
            print("未知错误，无法自动修复，停止重试。")
            break
        elif current_error_signature.startswith("generic_error"):
             print(f"检测到通用错误 ({current_error_signature})，无特定修复程序，停止重试。")
             break
        elif current_error_signature in ["no_log_content", "no_log_content_error", "log_read_error"]:
             print("无法读取日志或无内容，无法分析错误，停止重试。")
             break
        else:
             print(f"未处理的错误类型: {current_error_signature}，无自动修复程序，停止重试。")
             break

        # --- Prepare for next retry ---
        retry += 1
        if not fix_attempt_made_in_last_cycle:
             # Should not be reached if we break on unhandled errors
             print("未尝试修复，等待 2 秒...")
             time.sleep(2)


    # --- End of Loop ---
    print(f"\n--- 编译最终失败 ---")
    if retry > args.max_retry:
        print(f"已达到最大重试次数 ({args.max_retry})。")
    print(f"最后一次运行日志: {current_run_log}")
    print(f"最后检测到的错误: {last_error_signature}")
    return 1

if __name__ == "__main__":
    if not (Path("Makefile").exists() and Path("rules.mk").exists() and Path("package").is_dir()):
         print("错误：请在 OpenWrt 源码根目录运行此脚本。")
         sys.exit(2)
    sys.exit(main())
