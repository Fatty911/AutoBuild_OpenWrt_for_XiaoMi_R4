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

# --- Global variable for log content ---
log_content_global = ""

def get_relative_path(path):
    """获取相对路径，优先相对于当前工作目录"""
    current_pwd = os.getcwd()
    try:
        # Ensure path is absolute first if possible, handle potential errors
        abs_path = Path(path).resolve()
        # Check if it's within the current working directory
        # Use Path.cwd() for consistency
        if abs_path.is_relative_to(Path.cwd()):
            return str(abs_path.relative_to(Path.cwd()))
        else:
            # Return absolute path if outside CWD
            return str(abs_path)
    except (ValueError, OSError, Exception): # Handle various errors
        # Fallback to the original path string
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

    # --- Generic Error (fallback) ---
    generic_error_match = re.search(r'(error:|failed|fatal error:|collect2: error: ld returned 1 exit status)', log_content, re.IGNORECASE)
    if generic_error_match:
        error_keyword = generic_error_match.group(1).lower().split(':')[0].replace(' ', '_')
        context_line = ""
        for line in reversed(log_content.splitlines()):
             if generic_error_match.group(1).lower() in line.lower():
                 context_line = re.sub(r'\x1b\[[0-9;]*[mK]', '', line).strip() # Remove ANSI codes
                 context_line = re.sub(r'[^a-zA-Z0-9\s\._\-\+=:/]', '', context_line)[:80] # Keep relevant chars
                 break
        return f"generic_error:{error_keyword}:{context_line}"

    return "unknown_error"

# --- Fix Function ---
def fix_batman_adv_create_patch():
    """
    Fixes the implicit declaration error in batman-adv/net/batman-adv/multicast.c
    by creating a patch file in feeds/routing/batman-adv/patches/.
    """
    print("🔧 检测到 batman-adv multicast.c 错误，尝试创建修复补丁...")
    patch_created_or_existed = False
    patch_dir = Path("feeds/routing/batman-adv/patches")
    patch_filename = "0003-fix-multicast-implicit-declaration.patch" # Number higher than existing patches
    patch_path = patch_dir / patch_filename
    patch_path_rel = get_relative_path(str(patch_path))

    # Content of the patch
    patch_content = """--- a/net/batman-adv/multicast.c
+++ b/net/batman-adv/multicast.c
@@ -208,7 +208,7 @@
  */
 bool batadv_mcast_mla_rtr_flags_bridge_get(struct batadv_priv *bat_priv,
                                          struct net_device *dev)
-{
+{#
 -	if (!br_multicast_has_router_adjacent(dev, ETH_P_IP))
 +	if (!br_multicast_has_querier_adjacent(dev, ETH_P_IP))
 		return false;

"""

    try:
        if patch_path.exists():
            print(f"ℹ️ 补丁文件 '{patch_path_rel}' 已存在。")
            patch_created_or_existed = True
        else:
            print(f"创建补丁文件: {patch_path_rel}")
            # Create the patches directory if it doesn't exist
            patch_dir.mkdir(parents=True, exist_ok=True)
            with open(patch_path, 'w', encoding='utf-8') as f:
                f.write(patch_content)
            print(f"✅ 成功创建补丁文件 {patch_path_rel}。")
            patch_created_or_existed = True

    except Exception as e:
        print(f"❌ 创建或检查补丁文件 {patch_path_rel} 时出错: {e}")
        return False # Stop if we can't create the patch

    # Always clean the package after detecting the error to force re-patching
    # regardless of whether the patch was just created or already existed.
    print("🧹 清理 batman-adv 包以应用补丁...")
    clean_cmd = ["make", "package/feeds/routing/batman-adv/clean", "V=s"]
    try:
        result = subprocess.run(clean_cmd, check=False, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            # Don't treat clean failure as fatal for the fix attempt itself
            print(f"⚠️ batman-adv 清理可能失败 (返回码 {result.returncode}):\n{result.stderr[-500:]}")
        else:
            print("✅ batman-adv 清理完成。")
    except subprocess.TimeoutExpired:
         print("⚠️ 清理 batman-adv 时超时。")
    except Exception as e:
        print(f"⚠️ 执行清理命令时出错: {e}")

    # Return True because we've identified the error and taken the corrective action (creating patch + cleaning)
    return True

# --- Map Signatures to Fix Functions ---
FIX_FUNCTIONS = {
    "batman_adv_multicast_implicit_decl": fix_batman_adv_create_patch,
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
    same_error_count = 0
    global log_content_global

    while retry <= args.max_retry:
        current_run_log = f"{args.log_file}.run.{retry}.log"
        cmd = f"{base_cmd} -j{jobs}" # Apply -j here

        print(f"\n--- 尝试 {retry}/{args.max_retry} ---")
        print(f"运行命令: {cmd}")
        print(f"日志文件: {current_run_log}")

        status = -1
        process = None # Initialize process variable
        try:
            process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, encoding='utf-8', errors='replace', bufsize=1)

            with open(current_run_log, 'w', encoding='utf-8', errors='replace') as f:
                for line in iter(process.stdout.readline, ''):
                    sys.stdout.write(line)
                    f.write(line)
            status = process.wait()

        except KeyboardInterrupt:
             print("\n🛑 检测到中断信号，正在终止...")
             if process and process.poll() is None: # Check if process is still running
                 process.terminate()
                 try:
                     process.wait(timeout=5) # Wait a bit for termination
                 except subprocess.TimeoutExpired:
                     process.kill() # Force kill if terminate doesn't work
             sys.exit(130) # Standard exit code for Ctrl+C
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
        try:
            # Ensure file is closed before reading
            time.sleep(0.5) # Small delay just in case
            with open(current_run_log, 'r', encoding='utf-8', errors='replace') as f:
                log_content_global = f.read()
        except FileNotFoundError:
             print(f"❌ 无法读取日志文件: {current_run_log}")
             log_content_global = ""
             current_error_signature = "no_log_content_error"
        except Exception as e:
             print(f"❌ 读取日志文件时发生错误: {e}")
             log_content_global = ""
             current_error_signature = "log_read_error"
        else:
             current_error_signature = get_error_signature(log_content_global)

        print(f"检测到的错误签名: {current_error_signature}")

        # --- Consecutive Error Check ---
        # Only increment if it's the *specific* error we're trying to fix
        if current_error_signature == "batman_adv_multicast_implicit_decl":
            if last_error_signature == current_error_signature:
                same_error_count += 1
                print(f"连续相同 batman-adv 错误次数: {same_error_count + 1}")
                if same_error_count >= 1: # Stop after 2 consecutive identical errors post-patch attempt
                    print(f"错误 '{current_error_signature}' 在尝试修复后仍然连续出现，停止重试。")
                    break
            else:
                same_error_count = 0 # Reset if error changes or was different before
        else:
            # If a *different* error occurs after the fix attempt, stop immediately.
            if last_error_signature == "batman_adv_multicast_implicit_decl":
                 print(f"出现新的错误 '{current_error_signature}'，停止重试。")
                 break
            # Reset counter for other errors if needed, though we usually stop for them anyway
            same_error_count = 0


        last_error_signature = current_error_signature

        # --- Attempt Fixes ---
        fix_attempted = False
        if current_error_signature in FIX_FUNCTIONS:
            fix_func = FIX_FUNCTIONS[current_error_signature]
            fix_attempted = fix_func() # Pass no arguments if fix func doesn't need log
        elif current_error_signature == "unknown_error":
            print("未知错误，无法自动修复。")
        elif current_error_signature.startswith("generic_error"):
             print("检测到通用错误，无特定修复程序。")
        elif current_error_signature in ["no_log_content", "no_log_content_error", "log_read_error"]:
             print("无法读取日志或无内容，无法分析错误。")
        else:
             print(f"未处理的错误类型: {current_error_signature}，无自动修复程序。")

        # --- Prepare for next retry ---
        retry += 1
        if fix_attempted:
            # If the fix was attempted (patch created/existed + clean run),
            # proceed to the next retry immediately.
            print("已尝试修复 (创建/检查补丁并清理)，继续下一次尝试...")
            # No sleep needed here, let the next make run immediately
        else:
            # If no fix was attempted for the specific error, stop retrying.
            print("未找到适用的修复程序或修复未执行，停止重试。")
            break


    # --- End of Loop ---
    print(f"\n--- 编译最终失败 ---")
    if retry > args.max_retry:
        print(f"已达到最大重试次数 ({args.max_retry})。")
    print(f"最后一次运行日志: {current_run_log}")
    print(f"最后检测到的错误: {last_error_signature}")
    return 1

if __name__ == "__main__":
    # Ensure we are in the openwrt directory before running
    if not (Path("Makefile").exists() and Path("rules.mk").exists() and Path("package").is_dir()):
         print("错误：请在 OpenWrt 源码根目录运行此脚本。")
         sys.exit(2)
    sys.exit(main())
