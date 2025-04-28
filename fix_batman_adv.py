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
    # More specific regex matching the key parts of the error
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
def fix_batman_adv_multicast(log_content):
    """
    Fixes the implicit declaration error in batman-adv/net/batman-adv/multicast.c
    by replacing br_multicast_has_router_adjacent with br_multicast_has_querier_adjacent.
    """
    print("🔧 检测到 batman-adv multicast.c 错误，尝试修复...")
    fixed = False
    target_line_index = 210 # Line 211 is index 210
    old_func = "br_multicast_has_router_adjacent"
    new_func = "br_multicast_has_querier_adjacent"

    # Find the multicast.c file within the batman-adv build directory
    # Use glob to be more robust against slight path variations
    search_pattern = "build_dir/**/batman-adv-*/net/batman-adv/multicast.c"
    found_files = list(Path(".").glob(search_pattern))

    # Filter out potential matches in unrelated directories if necessary (e.g., tmp)
    # Typically, there should only be one relevant match in build_dir/target-*/linux-*/
    valid_files = [f for f in found_files if 'target-' in str(f) and 'linux-' in str(f)]

    if not valid_files:
        print(f"❌ 错误：找不到 batman-adv 的 multicast.c 文件 (搜索模式: {search_pattern})")
        return False
    if len(valid_files) > 1:
        print(f"⚠️ 警告：找到多个 multicast.c 文件，将使用第一个: {get_relative_path(str(valid_files[0]))}")
        print(f"   其他找到的文件: {[get_relative_path(str(f)) for f in valid_files[1:]]}")

    target_file = valid_files[0]
    target_file_rel = get_relative_path(str(target_file))
    print(f"找到目标文件: {target_file_rel}")

    try:
        with open(target_file, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        if len(lines) <= target_line_index:
            print(f"❌ 错误：文件 {target_file_rel} 行数 ({len(lines)}) 不足，无法修改第 {target_line_index + 1} 行。")
            return False

        current_line = lines[target_line_index]

        if new_func in current_line:
            print(f"ℹ️ 文件 {target_file_rel} 第 {target_line_index + 1} 行似乎已修复。")
            # Even if already fixed, cleaning might be necessary if build failed previously
            fixed = True # Indicate we should proceed with cleaning
        elif old_func in current_line:
            print(f"找到旧函数 '{old_func}' 在第 {target_line_index + 1} 行，进行替换...")
            backup_path = target_file.with_suffix(target_file.suffix + ".bak")
            try:
                shutil.copy2(target_file, backup_path)
                print(f"创建备份: {get_relative_path(str(backup_path))}")
            except Exception as backup_e:
                print(f"⚠️ 创建备份失败: {backup_e}")
                backup_path = None

            lines[target_line_index] = current_line.replace(old_func, new_func)

            with open(target_file, 'w', encoding='utf-8') as f:
                f.writelines(lines)

            # Verify fix
            with open(target_file, 'r', encoding='utf-8', errors='replace') as f_check:
                fixed_line = f_check.readlines()[target_line_index]
            if new_func in fixed_line:
                print(f"✅ 成功替换函数名于文件 {target_file_rel}。")
                fixed = True
                if backup_path and backup_path.exists():
                    try: os.remove(backup_path)
                    except OSError: pass
            else:
                print(f"❌ 替换失败，第 {target_line_index + 1} 行内容仍为: '{fixed_line.rstrip()}'")
                if backup_path and backup_path.exists():
                    try:
                        shutil.move(str(backup_path), target_file) # Restore backup
                        print("已恢复备份。")
                    except Exception as restore_e:
                         print(f"❌ 恢复备份失败: {restore_e}")
        else:
            print(f"❌ 错误：在文件 {target_file_rel} 第 {target_line_index + 1} 行未找到预期的函数 '{old_func}'。")
            print(f"   该行内容为: {current_line.rstrip()}")
            return False

    except Exception as e:
        print(f"❌ 处理文件 {target_file_rel} 时出错: {e}")
        return False

    # If the fix was applied or deemed already applied, clean the package
    if fixed:
        print("🧹 清理 batman-adv 包以应用更改...")
        clean_cmd = ["make", "package/feeds/routing/batman-adv/clean", "V=s"]
        try:
            result = subprocess.run(clean_cmd, check=False, capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                print(f"⚠️ batman-adv 清理失败:\n{result.stderr[-500:]}")
            else:
                print("✅ batman-adv 清理完成。")
        except subprocess.TimeoutExpired:
             print("❌ 清理 batman-adv 时超时。")
        except Exception as e:
            print(f"❌ 执行清理命令时出错: {e}")
        # Return True even if clean fails, as the primary fix was attempted/verified
        return True
    else:
        return False

# --- Map Signatures to Fix Functions ---
FIX_FUNCTIONS = {
    "batman_adv_multicast_implicit_decl": fix_batman_adv_multicast,
    # Add other error signatures and their fix functions here if needed
}

# --- Main Logic ---
def main():
    parser = argparse.ArgumentParser(description='OpenWrt Batman-adv 编译修复脚本')
    parser.add_argument('make_command', help='原始编译命令，例如 "make package/feeds/routing/batman-adv/compile V=s"')
    parser.add_argument('log_file', help='日志文件基础名 (不含 .run.N.log)')
    parser.add_argument('--max-retry', type=int, default=3, help='最大重试次数') # Lower default for specific fix
    # -j flag is often not relevant for single package compile, but keep for consistency
    parser.add_argument('--jobs', type=int, default=1, help='并行任务数 (通常为 1 用于包编译)')
    args = parser.parse_args()

    # Extract base command and ensure -j is set correctly
    base_cmd = re.sub(r'\s-j\s*\d+', '', args.make_command).strip()
    jobs = args.jobs if args.jobs > 0 else 1 # Default to 1 for package compile

    retry = 1
    last_error_signature = None
    same_error_count = 0
    global log_content_global

    while retry <= args.max_retry:
        current_run_log = f"{args.log_file}.run.{retry}.log"
        # Always use specified jobs for package compile
        cmd = f"{base_cmd} -j{jobs}"

        print(f"\n--- 尝试 {retry}/{args.max_retry} ---")
        print(f"运行命令: {cmd}")
        print(f"日志文件: {current_run_log}")

        status = -1 # Default status
        try:
            # Use Popen to stream output and write to log simultaneously
            process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, encoding='utf-8', errors='replace', bufsize=1) # Line buffered

            with open(current_run_log, 'w', encoding='utf-8', errors='replace') as f:
                for line in iter(process.stdout.readline, ''):
                    sys.stdout.write(line)
                    f.write(line)
            status = process.wait() # Get final return code

        except Exception as e:
            print(f"\n❌ 执行编译命令时发生异常: {e}")
            try:
                with open(current_run_log, 'a', encoding='utf-8', errors='replace') as f:
                    f.write(f"\n\n*** SCRIPT ERROR DURING EXECUTION ***\n{e}\n")
            except Exception: pass
            status = 1 # Assume failure

        # --- Process Results ---
        if status == 0:
            print("\n✅ 编译成功！")
            return 0

        print(f"\n❌ 编译失败 (返回码: {status})")

        # Read log content for error analysis
        try:
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
        if current_error_signature == last_error_signature and current_error_signature not in ["no_log_content", "unknown_error", "log_read_error", "generic_error"]:
            same_error_count += 1
            print(f"连续相同错误次数: {same_error_count + 1}")
            if same_error_count >= 1: # Stop after 2 consecutive identical specific errors
                print(f"错误 '{current_error_signature}' 连续出现 {same_error_count + 1} 次，停止重试。")
                break
        else:
            same_error_count = 0

        last_error_signature = current_error_signature

        # --- Attempt Fixes ---
        fix_attempted = False
        if current_error_signature in FIX_FUNCTIONS:
            fix_func = FIX_FUNCTIONS[current_error_signature]
            fix_attempted = fix_func(log_content_global)
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
            print("已尝试修复，等待 3 秒...")
            time.sleep(3)
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
    sys.exit(main())
