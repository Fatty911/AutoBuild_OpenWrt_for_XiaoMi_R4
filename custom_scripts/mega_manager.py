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


def upload_to_mega(skip_on_failure=False):
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
    run_mega_cmd(["rpc", "confirm", "-f"], check=False)
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
        
        result = run_mega_cmd(["put", local_file, f"{remote_path}/"], check=False, timeout=1800)
        
        if result.returncode == 0:
            print("上传完成")
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
    
    if skip_on_failure:
        print("警告: MEGA 上传失败，但 skip-on-failure 模式已启用，继续执行...")
        print("::warning::MEGA 上传失败，已跳过")
        return
    
    print("上传失败")
    sys.exit(1)


def download_from_mega(args, skip_on_failure=False):
    remote_folder = args.remote_folder
    dest_dir = args.dest_dir
    
    ensure_logged_in()
    
    temp_dir = os.path.join(dest_dir, ".mega_temp")
    os.makedirs(temp_dir, exist_ok=True)
    tempfile.tempdir = temp_dir
    os.environ["TMPDIR"] = temp_dir
    print(f"临时目录已设置为: {temp_dir}")
    
    remote_path = f"/{remote_folder}"
    
    result = run_mega_cmd(["ls", remote_path], check=False)
    if result.returncode != 0:
        error_msg = f"远程文件夹 {remote_path} 不存在"
        print(f"错误: {error_msg}")
        write_error_log("REMOTE_NOT_FOUND", error_msg, f"Remote path: {remote_path}")
        if skip_on_failure:
            print("警告: 远程文件夹不存在，但 skip-on-failure 模式已启用，继续执行...")
            print("::warning::MEGA 远程文件夹不存在，已跳过下载")
            return
        sys.exit(1)
    
    print(f"找到文件夹: {remote_folder}")
    
    os.makedirs(dest_dir, exist_ok=True)
    
    max_retries = 3
    retry_delay = 5
    last_error = ""
    
    for attempt in range(max_retries):
        print(f"从 {remote_path} 下载到 {dest_dir} (尝试 {attempt + 1}/{max_retries})")
        result = run_mega_cmd(["get", remote_path, dest_dir], check=False, timeout=1800)
        
        if result.returncode == 0:
            print("下载成功")
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
    
    if skip_on_failure:
        print("警告: MEGA 下载失败，但 skip-on-failure 模式已启用，继续执行...")
        print("::warning::MEGA 下载失败，已跳过")
        return
    
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
    result = run_mega_cmd(["rpc", "confirm", "-f"], check=False)
    
    if result.returncode == 0:
        print("回收站已清空，空间已彻底释放")
    else:
        result = run_mega_cmd(["emptytrash"], check=False)
        if result.returncode == 0:
            print("回收站已清空，空间已彻底释放")
        else:
            print("清空回收站失败（但文件已删除）")


def main():
    parser = argparse.ArgumentParser(description="MEGA 网盘管理工具 (使用 MEGAcmd)")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    parser_upload = subparsers.add_parser("upload", help="上传源码压缩包到 MEGA")
    parser_upload.add_argument("--skip-on-failure", action="store_true", 
                                help="上传失败时跳过而不是退出")
    parser_upload.add_argument("--error-log", dest="error_log", 
                                help="错误日志输出路径")
    
    parser_download = subparsers.add_parser("download", help="从 MEGA 下载源码压缩包")
    parser_download.add_argument("remote_folder", help="MEGA 远程文件夹名")
    parser_download.add_argument("dest_dir", help="本地目标目录")
    parser_download.add_argument("--skip-on-failure", action="store_true", 
                                  help="下载失败时跳过而不是退出")
    parser_download.add_argument("--error-log", dest="error_log", 
                                  help="错误日志输出路径")
    
    subparsers.add_parser("delete", help="删除 MEGA 上的临时源码压缩包")
    
    args = parser.parse_args()
    
    if args.command == "upload":
        if hasattr(args, 'error_log') and args.error_log:
            os.environ["MEGA_ERROR_LOG"] = args.error_log
        upload_to_mega(skip_on_failure=getattr(args, 'skip_on_failure', False))
    elif args.command == "download":
        if hasattr(args, 'error_log') and args.error_log:
            os.environ["MEGA_ERROR_LOG"] = args.error_log
        download_from_mega(args, skip_on_failure=getattr(args, 'skip_on_failure', False))
    elif args.command == "delete":
        delete_from_mega()


if __name__ == "__main__":
    main()
