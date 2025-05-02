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

    # --- Missing Kernel .config Error ---
    kernel_config_match = re.search(
        r"No rule to make target.*?(/linux-\d+\.\d+\.\d+)/\.config.*needed by.*?/(.*?)/\.built",
        log_content
    )
    if kernel_config_match:
        # kernel_dir_name = kernel_config_match.group(1) # e.g., linux-5.10.236
        failed_pkg_dir_name = kernel_config_match.group(2) # e.g., cryptodev-linux-cryptodev-linux-1.13
        # Try to get a cleaner package name
        pkg_name_match = re.match(r"([a-zA-Z0-9_-]+)-.*", failed_pkg_dir_name)
        pkg_name = pkg_name_match.group(1) if pkg_name_match else failed_pkg_dir_name
        return f"kernel_config_missing:{pkg_name}"

    # --- Batman-adv multicast.c implicit declaration error ---
    batman_adv_multicast_match = re.search(
        r"batman-adv/multicast\.c.*error: implicit declaration of function 'br_multicast_has_router_adjacent'.*?did you mean 'br_multicast_has_querier_adjacent'.*?make\[\d+\]: \*\*\* .*?batman-adv.*? Error \d+",
        log_content, re.DOTALL | re.IGNORECASE
    )
    if batman_adv_multicast_match:
        return "batman_adv_multicast_implicit_decl"
        

    # --- Batman-adv patch failed error (specifically 0003 if using pre-added patch) ---
    # batman_patch_failed_match = re.search(
    #     r"Applying.*?patches/0003-fix-multicast-implicit-declaration\.patch.*?FAILED.*?Patch failed!",
    #     log_content, re.DOTALL | re.IGNORECASE
    # )
    # if batman_patch_failed_match:
    #     return "batman_adv_patch_0003_failed"

    
    batman_patch_other_error = re.search(
        r"batman-adv.*Error",
        log_content, re.DOTALL | re.IGNORECASE
    )    
    if batman_patch_other_error:
        return "batman_patch_other_error"
    
    # --- Generic Error (fallback) ---
    generic_error_match = re.search(r'(error:|failed|fatal error:|collect2: error: ld returned 1 exit status)', log_content, re.IGNORECASE)
    if generic_error_match:
        pkg_fail_match = re.search(r"ERROR: package/(?:feeds/[^/]+/|kernel/|pkgs/|libs/|utils/|network/)?([^/]+) failed to build", log_content)
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

# --- Fix Functions ---

def clean_package(package_path):
    """Runs make clean for the specified package path."""
    if not package_path:
        print("⚠️ clean_package: 无效的包路径。")
        return False
    # Construct make target path relative to openwrt root
    # e.g., package/kernel/cryptodev-linux or feeds/routing/batman-adv
    make_target = f"{package_path}/clean"
    print(f"🧹 清理包: {make_target}...")
    clean_cmd = ["make", make_target, "V=s"]
    try:
        result = subprocess.run(clean_cmd, check=False, capture_output=True, text=True, timeout=120) # Increased timeout
        if result.returncode != 0:
            print(f"⚠️ 包清理可能失败 (命令: {' '.join(clean_cmd)}, 返回码 {result.returncode}):\n{result.stderr[-500:]}")
            # Don't necessarily return False, cleaning failure might not block progress
        else:
            print(f"✅ 包清理完成: {make_target}")
        return True # Indicate attempt was made
    except subprocess.TimeoutExpired:
         print(f"⚠️ 清理包时超时: {make_target}")
         return False # Timeout is likely a problem
    except Exception as e:
        print(f"⚠️ 执行清理命令时出错 ({make_target}): {e}")
        return False # Other exceptions likely indicate a problem

def fix_kernel_prepare(error_signature):
    """
    Fixes the missing kernel .config file by running 'make target/linux/prepare'.
    Also cleans the package that initially failed.
    """
    print("🔧 检测到内核 .config 缺失，运行 'make target/linux/prepare'...")

    # Extract the package name that failed from the signature
    failed_pkg_name = "unknown"
    if ":" in error_signature:
        failed_pkg_name = error_signature.split(":")[-1]

    prepare_cmd = ["make", "target/linux/prepare", "V=s", "-j1"] # Use -j1 for prepare step
    success = False
    try:
        result = subprocess.run(prepare_cmd, check=True, capture_output=True, text=True, timeout=600) # Long timeout for kernel prepare
        print(f"✅ 内核准备完成。 输出:\n{result.stdout[-500:]}")
        success = True
    except subprocess.CalledProcessError as e:
        print(f"❌ 内核准备失败 (命令: {' '.join(prepare_cmd)}, 返回码 {e.returncode}):")
        print(e.stderr[-1000:])
        print(e.stdout[-1000:])
    except subprocess.TimeoutExpired:
         print(f"❌ 内核准备超时: {' '.join(prepare_cmd)}")
    except Exception as e:
        print(f"❌ 执行内核准备时出错: {e}")

    # Try cleaning the package that failed due to the missing config, even if prepare failed
    if failed_pkg_name != "unknown":
        # Attempt to find the package path (this is heuristic)
        pkg_path = None
        possible_locations = [
            f"package/kernel/{failed_pkg_name}",
            f"package/feeds/*/{failed_pkg_name}",
            f"feeds/*/{failed_pkg_name}"
        ]
        for loc in possible_locations:
            found = list(Path(".").glob(loc))
            if found:
                # Prioritize non-feeds paths if multiple found
                non_feed_paths = [p for p in found if not p.parts[0].startswith('feeds')]
                if non_feed_paths:
                     pkg_path = non_feed_paths[0]
                else:
                     pkg_path = found[0]
                break
        if pkg_path:
             clean_package(str(pkg_path))
        else:
             print(f"⚠️ 无法定位包 '{failed_pkg_name}' 的路径进行清理。")

    return success # Return True only if 'make prepare' succeeded


def fix_batman_adv_patch_or_clean():
    """
    Handles the batman-adv implicit declaration error.
    Assumes a patch file '0003-...' exists (created manually).
    Cleans the package to ensure the patch is applied.
    """
    print("🔧 检测到 batman-adv multicast.c 错误，尝试清理包以应用预置补丁...")
    patch_path = Path("feeds/routing/batman-adv/patches/0003-fix-multicast-implicit-declaration.patch")
    if not patch_path.exists():
         print(f"❌ 错误：预期的补丁文件 '{get_relative_path(str(patch_path))}' 不存在！")
         print(f"  请先手动创建该补丁文件。")
         return False # Cannot proceed without the patch

    # Clean the package
    return clean_package("feeds/routing/batman-adv")


def handle_failed_patch_0003():
    """Handles the case where our pre-added patch 0003 failed to apply."""
    print("❌ 检测到预置补丁 0003 应用失败。")
    patch_path = Path("feeds/routing/batman-adv/patches/0003-fix-multicast-implicit-declaration.patch")
    patch_path_rel = get_relative_path(str(patch_path))
    print(f"  请检查补丁文件 '{patch_path_rel}' 的上下文是否与当前源码匹配。")
    print(f"  构建日志中的 .rej 文件可能包含详细信息。")
    # No automatic action here, requires manual patch fix.
    return False # Indicate automatic fix failed


def switch_to_official_batman_adv(error_signature):
    """
    Attempts to switch the routing feed to official OpenWrt and reinstall batman-adv.
    """
    print("🔧 检测到 coolsnowwolf batman-adv 编译失败，尝试切换到 OpenWrt 官方 routing feed...")

    feeds_conf_path = "feeds.conf.default"
    try:
        # 1. Modify feeds.conf.default
        print(f"   1. 修改 {feeds_conf_path}...")
        with open(feeds_conf_path, "r") as f:
            lines = f.readlines()
        with open(feeds_conf_path, "w") as f:
            found_cs = False
            found_owrt = False
            for line in lines:
                if line.strip().startswith("src-git routing https://github.com/coolsnowwolf/routing"):
                    f.write("#" + line) # Comment out coolsnowwolf
                    found_cs = True
                elif line.strip().startswith("src-git routing https://git.openwrt.org/feed/routing.git") or \
                     line.strip().startswith("src-git routing https://github.com/openwrt/routing.git"):
                     # Uncomment if exists and commented, otherwise keep as is
                     if line.startswith("#"):
                         f.write(line[1:])
                     else:
                         f.write(line)
                     found_owrt = True
                else:
                    f.write(line)
            if not found_owrt: # Add official feed if not present at all
                 # Prefer stable branch
                 f.write("\nsrc-git routing https://git.openwrt.org/feed/routing.git;openwrt-23.05\n")
                 print("      添加了 OpenWrt 官方 routing feed (openwrt-23.05)。")
            elif found_cs:
                 print("      注释了 coolsnowwolf routing feed。")
            else:
                 print("      coolsnowwolf routing feed 未找到，官方 feed 已存在或已添加。")


        # 2. Update the routing feed
        print("   2. 更新 routing feed...")
        update_cmd = ["./scripts/feeds", "update", "routing"]
        result = subprocess.run(update_cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"❌ 更新 routing feed 失败 (命令: {' '.join(update_cmd)}):\n{result.stderr[-500:]}")
            return False
        print("      ✅ routing feed 更新成功。")

        # 3. Uninstall old batman-adv package (might fail if not installed, ignore error)
        print("   3. 卸载旧的 batman-adv...")
        uninstall_cmd = ["./scripts/feeds", "uninstall", "batman-adv"]
        subprocess.run(uninstall_cmd, capture_output=True, text=True, timeout=60)
        print("      尝试卸载完成 (忽略错误)。")

        # 4. Install new batman-adv package
        print("   4. 安装新的 batman-adv...")
        install_cmd = ["./scripts/feeds", "install", "batman-adv"]
        result = subprocess.run(install_cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            print(f"❌ 安装 batman-adv 失败 (命令: {' '.join(install_cmd)}):\n{result.stderr[-500:]}")
            # Attempt to install dependencies explicitly? Maybe too complex here.
            return False
        print("      ✅ batman-adv 安装成功。")

        # 5. Clean the package build directory
        print("   5. 清理 batman-adv 构建目录...")
        clean_package("feeds/routing/batman-adv") # Use your existing clean function

        print("✅ 切换 batman-adv 到官方源完成，请重试编译。")
        return True # Return True to indicate a fix was attempted

    except Exception as e:
        print(f"❌ 切换 batman-adv 源时发生严重错误: {e}")
        return False
# --- Map Signatures to Fix Functions ---
FIX_FUNCTIONS = {
    "kernel_config_missing": fix_kernel_prepare, # Add handler for missing kernel config
    "batman_adv_multicast_implicit_decl": fix_batman_adv_patch_or_clean, # Use the cleaning approach
    # "batman_adv_patch_0003_failed": handle_failed_patch_0003,
    "batman_patch_other_error": switch_to_official_batman_adv
}

# --- Main Logic ---
def main():
    parser = argparse.ArgumentParser(description='OpenWrt 编译修复脚本')
    parser.add_argument('make_command', help='原始 make 命令')
    parser.add_argument('log_file', help='日志文件基础名')
    parser.add_argument('--max-retry', type=int, default=3, help='最大重试次数') # Increase slightly for kernel prepare
    parser.add_argument('--jobs', type=int, default=1, help='并行任务数')
    args = parser.parse_args()

    base_cmd = re.sub(r'\s-j\s*\d+', '', args.make_command).strip()
    jobs = args.jobs if args.jobs > 0 else 1

    retry = 1
    last_error_signature = None
    fix_attempt_made_in_last_cycle = False

    while retry <= args.max_retry:
        current_run_log = f"{args.log_file}.run.{retry}.log"
        # Apply -j flag here
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
             # Pass the signature itself to the fix function if needed
             current_error_signature = get_error_signature(log_content_global)


        print(f"检测到的错误签名: {current_error_signature}")

        # --- Stop if the fix was attempted and the *same* error persists or a *new* one occurs ---
        if fix_attempt_made_in_last_cycle:
             if current_error_signature == last_error_signature:
                  print(f"错误 '{current_error_signature}' 在尝试修复/清理后仍然出现，停止重试。")
                  break
             else:
                  print(f"出现新的错误 '{current_error_signature}' 在尝试修复 '{last_error_signature}' 后，停止重试。")
                  break

        last_error_signature = current_error_signature
        fix_attempt_made_in_last_cycle = False # Reset flag

        # --- Attempt Fixes ---
        fix_function_found = False
        for sig_pattern, fix_func in FIX_FUNCTIONS.items():
             # Allow prefix matching for signatures like kernel_config_missing:pkgname
             if current_error_signature.startswith(sig_pattern):
                  fix_function_found = True
                  # Pass the full signature to the fix function if it accepts an argument
                  import inspect
                  sig = inspect.signature(fix_func)
                  if len(sig.parameters) > 0:
                       if fix_func(current_error_signature): # Pass signature
                           fix_attempt_made_in_last_cycle = True
                       else:
                           print(f"修复函数针对 '{current_error_signature}' 执行但失败，停止重试。")
                           # Set status to non-zero to indicate failure and break loop
                           status = 1
                  else: # Fix function takes no arguments
                       if fix_func():
                            fix_attempt_made_in_last_cycle = True
                       else:
                            print(f"修复函数针对 '{current_error_signature}' 执行但失败，停止重试。")
                            status = 1
                  break # Stop checking other patterns once one matches

        if status != 0 and not fix_function_found:
             # Handle errors not in FIX_FUNCTIONS map
             if current_error_signature == "unknown_error":
                 print("未知错误，无法自动修复，停止重试。")
             elif current_error_signature.startswith("generic_error"):
                  print(f"检测到通用错误 ({current_error_signature})，无特定修复程序，停止重试。")
             elif current_error_signature in ["no_log_content", "no_log_content_error", "log_read_error"]:
                  print("无法读取日志或无内容，无法分析错误，停止重试。")
             else:
                  print(f"未处理的错误类型: {current_error_signature}，无自动修复程序，停止重试。")
             break # Stop loop if no fix function found or if fix failed

        # Break loop if fix function failed
        if status != 0 and not fix_attempt_made_in_last_cycle:
             break

        # --- Prepare for next retry ---
        retry += 1
        # No sleep needed if fix was attempted, proceed directly
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
    # Return the last non-zero status code, or 1 if loop finished normally but failed
    return status if status != 0 else 1

if __name__ == "__main__":
    # Ensure we are in the openwrt directory before running
    if not (Path("Makefile").exists() and Path("rules.mk").exists() and Path("package").is_dir()):
         print("错误：请在 OpenWrt 源码根目录运行此脚本。")
         sys.exit(2)
    sys.exit(main())
