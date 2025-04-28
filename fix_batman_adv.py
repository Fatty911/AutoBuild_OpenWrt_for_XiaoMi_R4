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

    # --- Batman-adv patch failed error ---
    # Detect if our specific patch failed to apply
    patch_failed_match = re.search(
        r"Applying.*?patches/0003-fix-multicast-implicit-declaration\.patch.*?Hunk #\d+ FAILED.*?Patch failed!",
        log_content, re.DOTALL | re.IGNORECASE
    )
    if patch_failed_match:
        return "batman_adv_patch_0003_failed" # Specific signature for our patch failing

    # --- Generic Error (fallback) ---
    generic_error_match = re.search(r'(error:|failed|fatal error:|collect2: error: ld returned 1 exit status)', log_content, re.IGNORECASE)
    if generic_error_match:
        # Try to get the package name from the "ERROR: package/... failed" line if available
        pkg_fail_match = re.search(r"ERROR: package/(?:feeds/[^/]+/|pkgs/|libs/|utils/|network/)?([^/]+) failed to build", log_content)
        pkg_name = pkg_fail_match.group(1) if pkg_fail_match else "unknown_pkg"

        error_keyword = generic_error_match.group(1).lower().split(':')[0].replace(' ', '_')
        context_line = ""
        for line in reversed(log_content.splitlines()):
             if generic_error_match.group(1).lower() in line.lower():
                 context_line = re.sub(r'\x1b\[[0-9;]*[mK]', '', line).strip() # Remove ANSI codes
                 context_line = re.sub(r'[^a-zA-Z0-9\s\._\-\+=:/]', '', context_line)[:80] # Keep relevant chars
                 break
        return f"generic_error:{error_keyword}:{pkg_name}:{context_line}"


    return "unknown_error"

# --- Fix Function ---
def fix_batman_adv_generate_patch():
    """
    Fixes the implicit declaration error in batman-adv/net/batman-adv/multicast.c
    by dynamically generating a patch file in feeds/routing/batman-adv/patches/
    based on the state of the file in build_dir.
    """
    print("🔧 检测到 batman-adv multicast.c 错误，尝试动态生成修复补丁...")
    patch_generated = False
    patch_dir = Path("feeds/routing/batman-adv/patches")
    patch_filename = "0003-fix-multicast-implicit-declaration.patch"
    patch_path = patch_dir / patch_filename
    patch_path_rel = get_relative_path(str(patch_path))

    target_line_num = 211 # Actual line number from error log
    target_line_index = target_line_num - 1
    old_func = "br_multicast_has_router_adjacent"
    new_func = "br_multicast_has_querier_adjacent"
    relative_file_path = "net/batman-adv/multicast.c" # Path relative to package source root

    # 1. Check if patch already exists
    if patch_path.exists():
        print(f"ℹ️ 补丁文件 '{patch_path_rel}' 已存在。假设修复已应用。")
        # Still clean the package to ensure it's applied correctly in the next run
        print("🧹 清理 batman-adv 包以确保补丁应用...")
        clean_package()
        return True # Indicate fix attempt was made (by checking existence + cleaning)

    # 2. Find the source file in build_dir
    # This file should be in the state *after* patches 0001 and 0002 were applied
    search_pattern = f"build_dir/**/batman-adv-*/{relative_file_path}"
    found_files = list(Path(".").glob(search_pattern))
    valid_files = [f for f in found_files if 'target-' in str(f) and 'linux-' in str(f)]

    if not valid_files:
        print(f"❌ 错误：找不到 batman-adv 的源文件 (搜索模式: {search_pattern})")
        return False
    if len(valid_files) > 1:
        print(f"⚠️ 警告：找到多个源文件，将使用第一个: {get_relative_path(str(valid_files[0]))}")

    source_file_in_build_dir = valid_files[0]
    source_file_rel = get_relative_path(str(source_file_in_build_dir))
    print(f"找到构建目录中的源文件: {source_file_rel}")

    # 3. Generate the patch dynamically
    backup_file = None
    temp_patch_file_path = None
    try:
        # Create a backup
        backup_file = source_file_in_build_dir.with_suffix(".orig")
        shutil.copy2(source_file_in_build_dir, backup_file)
        print(f"创建临时备份: {get_relative_path(str(backup_file))}")

        # Modify the file in build_dir *in place* temporarily
        with open(source_file_in_build_dir, 'r+', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
            if len(lines) <= target_line_index:
                print(f"❌ 错误：文件 {source_file_rel} 行数 ({len(lines)}) 不足，无法修改第 {target_line_num} 行。")
                raise ValueError("Line index out of bounds")

            current_line = lines[target_line_index]
            if old_func not in current_line:
                print(f"❌ 错误：在文件 {source_file_rel} 第 {target_line_num} 行未找到预期函数 '{old_func}'。")
                print(f"   该行内容为: {current_line.rstrip()}")
                raise ValueError("Function not found at expected line")

            print(f"在 {source_file_rel} 第 {target_line_num} 行临时替换函数...")
            lines[target_line_index] = current_line.replace(old_func, new_func)
            f.seek(0)
            f.writelines(lines)
            f.truncate()

        # Create a temporary file for the patch
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".patch", encoding='utf-8') as temp_patch_file:
            temp_patch_file_path = Path(temp_patch_file.name)
            diff_cmd = [
                "diff", "-u",
                str(backup_file.relative_to(Path.cwd())), # Use relative path for diff
                str(source_file_in_build_dir.relative_to(Path.cwd())) # Use relative path for diff
            ]
            print(f"生成 diff: {' '.join(diff_cmd)}")
            # Run diff and capture output
            diff_process = subprocess.run(diff_cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')

            # diff exits with 1 if differences are found, 0 if identical, >1 on error
            if diff_process.returncode > 1:
                 print(f"❌ diff 命令执行失败 (返回码 {diff_process.returncode}):")
                 print(diff_process.stderr)
                 raise RuntimeError("diff command failed")
            elif diff_process.returncode == 0:
                 print(f"⚠️ diff 未找到差异，文件可能已修复或修改失败？")
                 # Continue, maybe the file was already correct, but still clean.
            else:
                 # Process diff output to fix headers
                 print("处理 diff 输出以修正补丁头...")
                 diff_output = diff_process.stdout
                 # Replace the absolute/long paths in the --- and +++ lines
                 # Make the paths relative to the package source root
                 processed_diff = re.sub(r"^--- .*", f"--- a/{relative_file_path}", diff_output, count=1, flags=re.MULTILINE)
                 processed_diff = re.sub(r"^\+\+\+ .*", f"+++ b/{relative_file_path}", processed_diff, count=1, flags=re.MULTILINE)
                 temp_patch_file.write(processed_diff)
                 print(f"临时补丁写入: {temp_patch_file_path}")


        # Move the generated patch to the correct location
        if temp_patch_file_path and temp_patch_file_path.stat().st_size > 0: # Check if patch has content
            patch_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(temp_patch_file_path), patch_path)
            print(f"✅ 成功生成并移动补丁到: {patch_path_rel}")
            patch_generated = True
        elif temp_patch_file_path: # If file exists but is empty
             print(f"ℹ️ 生成的补丁为空，未移动。")
             temp_patch_file_path.unlink() # Clean up empty temp file
             patch_generated = False # Consider it not generated if empty
        else:
             patch_generated = False # Not generated if diff failed etc.

    except Exception as e:
        print(f"❌ 生成动态补丁时出错: {e}")
        patch_generated = False # Ensure flag is false on error
    finally:
        # Restore the original file in build_dir from backup
        if backup_file and backup_file.exists():
            print(f"恢复原始文件: {source_file_rel}")
            try:
                shutil.move(str(backup_file), source_file_in_build_dir)
            except Exception as restore_e:
                 print(f"⚠️ 恢复备份文件失败: {restore_e}")
                 # This is problematic, the build dir is now modified...
                 # Try to delete the modified file? Or just leave it?
                 # Let's leave it for now, clean should handle it.
        # Clean up temp patch file if it still exists (e.g., was empty)
        if temp_patch_file_path and temp_patch_file_path.exists():
            try: temp_patch_file_path.unlink()
            except OSError: pass


    # 4. Clean the package to apply the patch on the next run
    print("🧹 清理 batman-adv 包以应用补丁...")
    clean_package()

    # Return True if the patch was generated or already existed
    return patch_generated or patch_path.exists()

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

def handle_failed_patch():
    """Handles the case where our generated patch failed to apply."""
    print("❌ 检测到之前生成的补丁应用失败。")
    patch_path = Path("feeds/routing/batman-adv/patches/0003-fix-multicast-implicit-declaration.patch")
    patch_path_rel = get_relative_path(str(patch_path))
    if patch_path.exists():
        print(f"尝试删除无效补丁: {patch_path_rel}")
        try:
            patch_path.unlink()
            print("✅ 已删除补丁。将在下次尝试重新生成。")
            # Clean again to ensure the failed patch state is cleared
            clean_package()
            return True # Indicate action was taken
        except Exception as e:
            print(f"❌ 删除补丁失败: {e}")
            return False
    else:
        print("ℹ️ 未找到需要删除的补丁文件。")
        return False


# --- Map Signatures to Fix Functions ---
FIX_FUNCTIONS = {
    "batman_adv_multicast_implicit_decl": fix_batman_adv_generate_patch,
    "batman_adv_patch_0003_failed": handle_failed_patch, # Handle if our patch fails
    # Add other error signatures and their fix functions here if needed
}

# --- Main Logic ---
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
                # Ensure stdout/stderr are properly handled even if script is interrupted
                for line in iter(process.stdout.readline, ''):
                    sys.stdout.write(line)
                    f.write(line)
            process.stdout.close() # Close stdout pipe
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
            # Ensure file is closed before reading
            if process: process.wait() # Ensure process finished writing
            time.sleep(0.2) # Short delay
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
        # If the *same* specific error occurs immediately after we tried to fix it, stop.
        if fix_attempt_made_in_last_cycle and current_error_signature == last_error_signature:
             if current_error_signature == "batman_adv_multicast_implicit_decl":
                 print(f"错误 '{current_error_signature}' 在尝试修复后仍然立即出现，停止重试。")
                 break
             elif current_error_signature == "batman_adv_patch_0003_failed":
                  print(f"补丁应用 '{current_error_signature}' 在尝试修复后仍然失败，停止重试。")
                  break
        # If a *different* error occurs right after the fix attempt, stop.
        elif fix_attempt_made_in_last_cycle and current_error_signature != last_error_signature:
             print(f"出现新的错误 '{current_error_signature}' 在尝试修复 '{last_error_signature}' 后，停止重试。")
             break

        last_error_signature = current_error_signature
        fix_attempt_made_in_last_cycle = False # Reset flag for this cycle

        # --- Attempt Fixes ---
        if current_error_signature in FIX_FUNCTIONS:
            fix_func = FIX_FUNCTIONS[current_error_signature]
            if fix_func(): # Run the fix function
                 fix_attempt_made_in_last_cycle = True # Mark that a fix was attempted
            else:
                 # If fix function returns False (e.g., couldn't find file, patch exists but clean fails?)
                 print(f"修复函数针对 '{current_error_signature}' 执行但可能未成功完成所有步骤，停止重试。")
                 break
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
             break # Stop for any other unhandled error

        # --- Prepare for next retry ---
        retry += 1
        # No sleep needed if fix was attempted, proceed directly
        if not fix_attempt_made_in_last_cycle:
             # This case should ideally not be reached if we break on unhandled errors
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
