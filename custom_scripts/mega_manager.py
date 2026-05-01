#!/usr/bin/env python3
"""
MEGA 网盘统一管理脚本 (上传、下载、删除)
使用 MEGAcmd 官方CLI工具操作 MEGA 网盘。

用法:
  python3 mega_manager.py upload
  python3 mega_manager.py download <remote_folder> <dest_dir>
  python3 mega_manager.py delete

环境变量要求:
  MEGA_USERNAME: MEGA 账号
  MEGA_PASSWORD: MEGA 密码
  SOURCE: 用于 upload 和 delete 操作的目标文件夹/文件前缀
"""

import os
import subprocess
import sys
import argparse
import calendar
import time
import tempfile
import re
import shutil

# ============================================================
# 传输速率验证配置
# GitHub Actions 网络较好时可达 ~100 MB/s
# 如果实际速度超过 200 MB/s，肯定是假传输（不可能这么快）
# 只检测"过快"，不检测"过慢"（慢的话6小时超时是正常的）
# ============================================================
MAX_TRANSFER_RATE_BYTES_PER_SEC = 200 * 1024 * 1024  # 200 MB/s


def run_mega_cmd(args, check=True, capture_output=True, timeout=None):
    cmd = ["mega-" + args[0]] + args[1:]
    print(f"执行: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=capture_output,
            text=True,
            check=False,
            timeout=timeout
        )
    except subprocess.TimeoutExpired:
        print(f"命令超时 ({timeout}秒)")
        return subprocess.CompletedProcess(cmd, returncode=124, stdout="", stderr=f"命令超时 ({timeout}秒)")
    except FileNotFoundError:
        print(f"命令不存在: {cmd[0]}")
        return subprocess.CompletedProcess(cmd, returncode=127, stdout="", stderr=f"命令不存在: {cmd[0]}")
    
    if result.stdout:
        print(result.stdout.strip())
    if result.stderr and result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    
    if check and result.returncode != 0:
        print(f"命令失败，退出码: {result.returncode}")
        sys.exit(1)
    
    return result


def ensure_logged_in():
    """确保已登录 MEGA 账号"""
    username = os.getenv("MEGA_USERNAME")
    password = os.getenv("MEGA_PASSWORD")
    
    if not (username and password):
        print("错误: 请设置 MEGA_USERNAME 和 MEGA_PASSWORD 环境变量")
        sys.exit(1)
    
    # 检查是否已登录
    result = run_mega_cmd(["whoami"], check=False)
    if result.returncode == 0 and username in result.stdout:
        print("已登录 MEGA 账号")
        return
    
    # 登录
    print("登录 MEGA 账号...")
    result = run_mega_cmd(["login", username, password], check=False)
    if result.returncode != 0:
        print(f"登录失败: {result.stderr}")
        sys.exit(1)
    print("登录成功")


def get_file_mtime(filepath):
    return os.path.getmtime(filepath)



def get_remote_file_mtime(remote_folder, filename):
    result = run_mega_cmd(["ls", "-l", "--time-format=ISO6081_WITH_TIME", f"/{remote_folder}"], check=False, capture_output=True)
    if result.returncode != 0:
        return None
    
    print(f"MEGA ls 输出:\n{result.stdout}")
    
    for line in result.stdout.strip().split('\n'):
        if filename in line:
            print(f"找到文件行: {line}")
            parts = line.split()
            if len(parts) >= 5:
                datetime_part = parts[-2] if len(parts) >= 6 else ""
                if "T" in datetime_part:
                    try:
                        from datetime import datetime
                        dt = datetime.strptime(datetime_part, "%Y-%m-%dT%H:%M:%S")
                        mtime = calendar.timegm(dt.timetuple())
                        print(f"远程文件时间戳: {mtime} (UTC)")
                        return mtime
                    except ValueError:
                        pass
    return None


def write_error_log(error_type, message, details=""):
    error_log_path = os.getenv("MEGA_ERROR_LOG", "/tmp/mega_error.log")
    try:
        with open(error_log_path, "w") as f:
            f.write(f"=== MEGA Upload Error ===\n")
            f.write(f"Error Type: {error_type}\n")
            f.write(f"Message: {message}\n")
            if details:
                f.write(f"\nDetails:\n{details}\n")
        print(f"错误日志已写入: {error_log_path}")
    except Exception as e:
        print(f"写入错误日志失败: {e}")


def upload_to_mega():
    source = os.getenv("SOURCE")
    if not source:
        print("错误: 请设置 SOURCE 环境变量")
        write_error_log("CONFIG_ERROR", "SOURCE 环境变量未设置")
        sys.exit(1)
    
    ensure_logged_in()
    
    possible_paths = [
        f"/workdir/{source}.tar.gz",
        f"{source}.tar.gz",
        f"./{source}.tar.gz",
    ]
    
    local_file = None
    for path in possible_paths:
        print(f"检查文件路径: {path} -> 存在: {os.path.exists(path)}")
        if os.path.exists(path):
            local_file = path
            break
    
    if not local_file:
        error_msg = f"未找到本地文件 {source}.tar.gz"
        print(f"错误: {error_msg}")
        print(f"已检查路径: {possible_paths}")
        print(f"当前工作目录: {os.getcwd()}")
        if os.path.exists("/workdir"):
            print("/workdir 目录内容:", os.listdir("/workdir"))
        write_error_log("FILE_NOT_FOUND", error_msg, f"Checked paths: {possible_paths}")
        sys.exit(1)
    
    local_mtime = get_file_mtime(local_file)
    print(f"本地文件时间戳: {local_mtime}")
    
    remote_path = f"/{source}"
    target_filename = f"{source}.tar.gz"
    
    run_mega_cmd(["mkdir", "-p", remote_path], check=False)
    
    print("=== 上传前清理 MEGA 网盘空间 ===")
    
    ls_result = run_mega_cmd(["ls", remote_path], check=False, capture_output=True)
    if ls_result.returncode == 0 and ls_result.stdout.strip():
        print(f"网盘文件夹 /{source}/ 当前内容:")
        print(ls_result.stdout.strip())
        for line in ls_result.stdout.strip().split('\n'):
            clean_line = line.strip().rstrip(':')
            # mega-ls output: folder title lines end with ':', file lines are bare filenames
            if clean_line and not clean_line.startswith('/') and clean_line != source:
                file_to_delete = f"/{source}/{clean_line}"
                print(f"删除旧文件: {file_to_delete}")
                rm_result = run_mega_cmd(["rm", "-f", file_to_delete], check=False)
                if rm_result.returncode != 0:
                    print(f"删除失败，尝试直接路径: /{source}/{clean_line}")
                    run_mega_cmd(["rm", "-f", f"/{source}/{clean_line}"], check=False)
    
    # mega-put may deposit files at root level instead of inside the target folder
    root_ls_result = run_mega_cmd(["ls", "/"], check=False, capture_output=True)
    if root_ls_result.returncode == 0 and root_ls_result.stdout.strip():
        for line in root_ls_result.stdout.strip().split('\n'):
            clean_line = line.strip().rstrip(':')
            if target_filename in clean_line and clean_line != source:
                print(f"删除根目录残留文件: /{clean_line}")
                run_mega_cmd(["rm", "-f", f"/{clean_line}"], check=False)
    
    all_folders_result = run_mega_cmd(["ls", "/"], check=False, capture_output=True)
    if all_folders_result.returncode == 0 and all_folders_result.stdout.strip():
        for line in all_folders_result.stdout.strip().split('\n'):
            folder_name = line.strip().rstrip(':')
            if folder_name and folder_name != source:
                folder_ls = run_mega_cmd(["ls", f"/{folder_name}"], check=False, capture_output=True)
                if folder_ls.returncode == 0 and folder_ls.stdout.strip():
                    for fline in folder_ls.stdout.strip().split('\n'):
                        fname = fline.strip()
                        if fname and '.tar.gz' in fname:
                            print(f"删除其他文件夹中的旧构建文件: /{folder_name}/{fname}")
                            run_mega_cmd(["rm", "-f", f"/{folder_name}/{fname}"], check=False)
    
    print("清空 MEGA 回收站以彻底释放空间...")
    run_mega_cmd(["emptytrash"], check=False)
    time.sleep(3)
    
    du_result = run_mega_cmd(["du"], check=False, capture_output=True)
    if du_result.returncode == 0:
        print(f"MEGA 网盘当前使用量: {du_result.stdout.strip()}")
    
    print("=== MEGA 网盘空间清理完成 ===")
    
    file_size_mb = os.path.getsize(local_file) / (1024 * 1024)
    print(f"文件大小: {file_size_mb:.2f} MB")
    print(f"开始上传: {local_file} -> MEGA:/{source}/")
    
    max_retries = 3
    retry_delay = 5
    last_error = ""
    
    for attempt in range(max_retries):
        print(f"上传尝试 {attempt + 1}/{max_retries}...")

        upload_start = time.time()
        # 动态超时: 最大6小时（GitHub Actions 默认限制）
        dynamic_timeout = 21600
        print(f"动态超时设为 {dynamic_timeout}s (文件 {file_size_mb:.2f}MB)")

        result = run_mega_cmd(["put", local_file, f"{remote_path}/"], check=False, timeout=dynamic_timeout)
        elapsed = time.time() - upload_start
        print(f"实际耗时: {elapsed:.2f} 秒")

        # --- 速率合理性检查：只检测"过快" ---
        # 按 200MB/s 计算最小合理时间，如果比这个还短就是假传输
        min_reasonable_time = os.path.getsize(local_file) / MAX_TRANSFER_RATE_BYTES_PER_SEC
        if elapsed < min_reasonable_time:
            actual_rate = os.path.getsize(local_file) / elapsed / (1024 * 1024)
            print(f"[速率异常] 实际耗时 {elapsed:.0f}s 小于最小合理时间 {min_reasonable_time:.0f}s "
                  f"(实际速度 {actual_rate:.0f}MB/s > 最大合理速度 200MB/s)，疑似假传输!")
            last_error = f"Upload too fast: {elapsed:.0f}s < {min_reasonable_time:.0f}s ({actual_rate:.0f}MB/s > 200MB/s)"
            if attempt < max_retries - 1:
                print(f"等待 {retry_delay} 秒后重试...")
                time.sleep(retry_delay)
                retry_delay *= 2
            continue

        if result.returncode == 0:
            print("上传命令完成，正在验证文件...")

            # 验证：检查文件是否存在于 MEGA 网盘
            ls_result = run_mega_cmd(["ls", remote_path], check=False, capture_output=True)
            if ls_result.returncode != 0 or target_filename not in ls_result.stdout:
                print(f"验证失败: 文件 {target_filename} 不在 MEGA:{remote_path}/ 中")
                print(f"mega-ls 输出: {ls_result.stdout}")
                last_error = "Upload verification failed: file not found on MEGA"
                if attempt < max_retries - 1:
                    print(f"等待 {retry_delay} 秒后重试...")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                continue

            # 验证：检查 MEGA 网盘使用量是否增加
            du_result = run_mega_cmd(["du"], check=False, capture_output=True)
            if du_result.returncode == 0:
                print(f"MEGA 网盘使用量: {du_result.stdout.strip()}")
                # 检查是否包含合理的存储使用量（至少 1GB）
                if "Total storage used:" in du_result.stdout:
                    # 提取存储量数值
                    import re
                    match = re.search(r'Total storage used:\s*(\d+)', du_result.stdout)
                    if match:
                        storage_bytes = int(match.group(1))
                        expected_bytes = int(file_size_mb * 1024 * 1024)
                        # 允许 10% 的误差（MEGA 可能压缩）
                        if storage_bytes < expected_bytes * 0.5:
                            print(f"警告: MEGA 存储量 ({storage_bytes} bytes) 远小于预期 ({expected_bytes} bytes)")
                            last_error = f"Storage mismatch: {storage_bytes} < {expected_bytes * 0.5}"
                            if attempt < max_retries - 1:
                                print(f"等待 {retry_delay} 秒后重试...")
                                time.sleep(retry_delay)
                                retry_delay *= 2
                            continue

            print("上传验证通过")
            return
        
        last_error = result.stderr or result.stdout or "Unknown error"
        print(f"上传失败 (尝试 {attempt + 1}/{max_retries}): {last_error}")
        
        if attempt < max_retries - 1:
            print(f"等待 {retry_delay} 秒后重试...")
            time.sleep(retry_delay)
            retry_delay *= 2
    
    error_details = f"""
文件: {local_file}
大小: {file_size_mb:.2f} MB
目标路径: MEGA:/{source}/
重试次数: {max_retries}
最后错误: {last_error}
工作目录: {os.getcwd()}
"""
    write_error_log("UPLOAD_FAILED", "MEGA 上传失败，重试次数已用尽", error_details)
    
    print("上传失败，Phase 1 编译产物未上传到 MEGA，Phase 2 将无法运行")
    sys.exit(1)


def download_from_mega(args):
    remote_folder = args.remote_folder
    dest_dir = args.dest_dir
    
    ensure_logged_in()
    
    temp_dir = os.path.join(dest_dir, ".mega_temp")
    os.makedirs(temp_dir, exist_ok=True)
    tempfile.tempdir = temp_dir
    os.environ["TMPDIR"] = temp_dir
    print(f"临时目录已设置为: {temp_dir}")
    
    remote_path = f"/{remote_folder}"
    expected_filename = f"{remote_folder}.tar.gz"
    
    result = run_mega_cmd(["ls", remote_path], check=False)
    if result.returncode != 0:
        error_msg = f"远程文件夹 {remote_path} 不存在"
        print(f"错误: {error_msg}")
        write_error_log("REMOTE_NOT_FOUND", error_msg, f"Remote path: {remote_path}")
        sys.exit(1)
    
    print(f"找到文件夹: {remote_folder}")
    
    # 获取远程文件大小用于验证
    ls_result = run_mega_cmd(["ls", "-l", remote_path], check=False, capture_output=True)
    remote_file_size = None
    if ls_result.returncode == 0:
        for line in ls_result.stdout.strip().split('\n'):
            if expected_filename in line:
                parts = line.split()
                if len(parts) >= 4:
                    try:
                        remote_file_size = int(parts[3])
                        print(f"远程文件大小: {remote_file_size} bytes ({remote_file_size / (1024*1024):.2f} MB)")
                    except ValueError:
                        pass
    
    os.makedirs(dest_dir, exist_ok=True)
    
    max_retries = 3
    retry_delay = 5
    last_error = ""
    
    for attempt in range(max_retries):
        print(f"从 {remote_path} 下载到 {dest_dir} (尝试 {attempt + 1}/{max_retries})")

        download_start = time.time()
        # 动态超时: 最大6小时（GitHub Actions 默认限制）
        dynamic_timeout = 21600
        if remote_file_size:
            print(f"动态超时设为 {dynamic_timeout}s (远程文件 {remote_file_size/(1024*1024):.2f}MB)")
        else:
            print(f"动态超时设为 {dynamic_timeout}s (未知远程文件大小)")

        result = run_mega_cmd(["get", remote_path, dest_dir], check=False, timeout=dynamic_timeout)
        elapsed = time.time() - download_start
        print(f"实际耗时: {elapsed:.2f} 秒")

        # --- 速率合理性检查：只检测"过快" ---
        if remote_file_size:
            min_reasonable_time = remote_file_size / MAX_TRANSFER_RATE_BYTES_PER_SEC
            if elapsed < min_reasonable_time:
                actual_rate = remote_file_size / elapsed / (1024 * 1024)
                print(f"[速率异常] 实际耗时 {elapsed:.0f}s 小于最小合理时间 {min_reasonable_time:.0f}s "
                      f"(实际速度 {actual_rate:.0f}MB/s > 最大合理速度 200MB/s)，疑似假传输!")
                last_error = f"Download too fast: {elapsed:.0f}s < {min_reasonable_time:.0f}s ({actual_rate:.0f}MB/s > 200MB/s)"
                if attempt < max_retries - 1:
                    print(f"等待 {retry_delay} 秒后重试...")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                continue
        
        if result.returncode == 0:
            print("下载命令完成，正在验证文件...")
            
            # 验证下载结果：mega-get 可能下载到文件夹或直接文件
            downloaded_file = None
            possible_paths = [
                os.path.join(dest_dir, expected_filename),  # 直接下载文件
                os.path.join(dest_dir, remote_folder, expected_filename),  # 下载文件夹
            ]
            
            for path in possible_paths:
                if os.path.exists(path):
                    downloaded_file = path
                    print(f"找到下载文件: {path}")
                    break
            
            if not downloaded_file:
                print("验证失败: 未找到下载的文件")
                print(f"检查路径: {possible_paths}")
                print(f"目录内容: {os.listdir(dest_dir)}")
                last_error = "Download verification failed: file not found locally"
                if attempt < max_retries - 1:
                    print(f"等待 {retry_delay} 秒后重试...")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                continue
            
            # 验证文件大小
            local_file_size = os.path.getsize(downloaded_file)
            print(f"本地文件大小: {local_file_size} bytes ({local_file_size / (1024*1024):.2f} MB)")
            
            if local_file_size < 1000000:  # 小于 1MB
                print(f"验证失败: 文件太小 ({local_file_size} bytes)")
                last_error = f"File too small: {local_file_size} bytes"
                # 删除损坏的文件
                os.remove(downloaded_file)
                if attempt < max_retries - 1:
                    print(f"等待 {retry_delay} 秒后重试...")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                continue
            
            # 如果知道远程大小，验证大小是否匹配（允许 10% 误差）
            if remote_file_size:
                size_ratio = local_file_size / remote_file_size
                if size_ratio < 0.9 or size_ratio > 1.1:
                    print(f"验证失败: 文件大小不匹配 (本地 {local_file_size} vs 远程 {remote_file_size})")
                    last_error = f"Size mismatch: {local_file_size} vs {remote_file_size}"
                    os.remove(downloaded_file)
                    if attempt < max_retries - 1:
                        print(f"等待 {retry_delay} 秒后重试...")
                        time.sleep(retry_delay)
                        retry_delay *= 2
                    continue
            
            # 如果下载的是文件夹，将文件移动到预期位置
            if downloaded_file != os.path.join(dest_dir, expected_filename):
                print(f"移动文件到预期位置: {downloaded_file} -> {os.path.join(dest_dir, expected_filename)}")
                import shutil
                shutil.move(downloaded_file, os.path.join(dest_dir, expected_filename))
                # 删除空文件夹
                folder_path = os.path.join(dest_dir, remote_folder)
                if os.path.exists(folder_path):
                    try:
                        os.rmdir(folder_path)
                    except OSError:
                        pass  # 文件夹非空，忽略
            
            print("下载验证通过")
            return
        
        last_error = result.stderr or result.stdout or "Unknown error"
        
        if "exeeded your available storage" in last_error.lower() or "storage" in last_error.lower():
            print("警告: MEGA 存储空间超出限制，无法下载")
            write_error_log("STORAGE_EXCEEDED", "MEGA 存储空间超出限制", 
                          f"Remote: {remote_path}\nDest: {dest_dir}\nError: {last_error}")
            break
        
        print(f"下载失败 (尝试 {attempt + 1}/{max_retries}): {last_error}")
        
        if attempt < max_retries - 1:
            print(f"等待 {retry_delay} 秒后重试...")
            time.sleep(retry_delay)
            retry_delay *= 2
    
    error_details = f"""
远程路径: {remote_path}
目标目录: {dest_dir}
重试次数: {max_retries}
最后错误: {last_error}
"""
    write_error_log("DOWNLOAD_FAILED", "MEGA 下载失败", error_details)
    
    print("下载失败，重试次数用尽")
    sys.exit(1)


def delete_from_mega():
    source = os.getenv("SOURCE")
    if not source:
        print("错误: 请设置 SOURCE 环境变量")
        sys.exit(1)
    
    ensure_logged_in()
    
    remote_path = f"/{source}"
    target_filename = f"{source}.tar.gz"
    
    result = run_mega_cmd(["ls", remote_path], check=False)
    if result.returncode != 0:
        print(f"文件夹 '{source}' 不存在，无需清理")
        return
    
    file_path = f"/{remote_path}/{target_filename}"
    result = run_mega_cmd(["ls", file_path], check=False)
    
    if result.returncode != 0:
        print(f"未找到文件 '{target_filename}'，无需清理")
        return
    
    print(f"永久删除网盘文件: MEGA:/{source}/{target_filename}")
    result = run_mega_cmd(["rm", "-f", file_path], check=False)
    
    if result.returncode == 0:
        print("文件删除成功")
    else:
        print(f"删除文件失败: {result.stderr}")
        return
    
    print("正在清空 MEGA 回收站以彻底释放空间...")
    result = run_mega_cmd(["emptytrash"], check=False)
    
    if result.returncode == 0:
        print("回收站已清空，空间已彻底释放")
    else:
        print("清空回收站失败（但文件已删除）")


def main():
    parser = argparse.ArgumentParser(description="MEGA 网盘管理工具 (使用 MEGAcmd)")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    parser_upload = subparsers.add_parser("upload", help="上传源码压缩包到 MEGA")
    parser_upload.add_argument("--error-log", dest="error_log", 
                                help="错误日志输出路径")
    
    parser_download = subparsers.add_parser("download", help="从 MEGA 下载源码压缩包")
    parser_download.add_argument("remote_folder", help="MEGA 远程文件夹名")
    parser_download.add_argument("dest_dir", help="本地目标目录")
    parser_download.add_argument("--error-log", dest="error_log", 
                                  help="错误日志输出路径")
    
    subparsers.add_parser("delete", help="删除 MEGA 上的临时源码压缩包")
    
    args = parser.parse_args()
    
    if args.command == "upload":
        if hasattr(args, 'error_log') and args.error_log:
            os.environ["MEGA_ERROR_LOG"] = args.error_log
        upload_to_mega()
    elif args.command == "download":
        if hasattr(args, 'error_log') and args.error_log:
            os.environ["MEGA_ERROR_LOG"] = args.error_log
        download_from_mega(args)
    elif args.command == "delete":
        delete_from_mega()


if __name__ == "__main__":
    main()
