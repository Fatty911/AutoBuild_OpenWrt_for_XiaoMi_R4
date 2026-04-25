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
        sys.exit(1)
    
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
                        mtime = int(dt.timestamp())
                        print(f"远程文件时间戳: {mtime}")
                        return mtime
                    except ValueError:
                        pass
    return None


def upload_to_mega():
    source = os.getenv("SOURCE")
    if not source:
        print("错误: 请设置 SOURCE 环境变量")
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
        print(f"错误: 未找到本地文件 {source}.tar.gz")
        print(f"已检查路径: {possible_paths}")
        print(f"当前工作目录: {os.getcwd()}")
        if os.path.exists("/workdir"):
            print("/workdir 目录内容:", os.listdir("/workdir"))
        sys.exit(1)
    
    local_mtime = get_file_mtime(local_file)
    print(f"本地文件时间戳: {local_mtime}")
    
    remote_path = f"/{source}"
    target_filename = f"{source}.tar.gz"
    
    run_mega_cmd(["mkdir", "-p", remote_path], check=False)
    
    remote_mtime = get_remote_file_mtime(source, target_filename)
    
    if remote_mtime is not None:
        print(f"网盘中存在同名文件，时间戳: {remote_mtime}，本地时间戳: {local_mtime:.0f}")
        
        if remote_mtime < local_mtime:
            print(f"网盘文件较旧，删除后重新上传: {target_filename}")
            run_mega_cmd(["rm", "-f", f"/{remote_path}/{target_filename}"], check=False)
        else:
            print(f"网盘文件不比本地旧（remote={remote_mtime} >= local={local_mtime:.0f}），跳过上传")
            sys.exit(0)
    
    print(f"开始上传: {local_file} -> MEGA:/{source}/")
    
    result = run_mega_cmd(["put", local_file, f"{remote_path}/"], timeout=1800)
    
    if result.returncode == 0:
        print("上传完成")
    else:
        print("上传失败")
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
    
    result = run_mega_cmd(["ls", remote_path], check=False)
    if result.returncode != 0:
        print(f"错误: 远程文件夹 {remote_path} 不存在")
        sys.exit(1)
    
    print(f"找到文件夹: {remote_folder}")
    
    os.makedirs(dest_dir, exist_ok=True)
    
    max_retries = 3
    for attempt in range(max_retries):
        print(f"从 {remote_path} 下载到 {dest_dir} (尝试 {attempt + 1}/{max_retries})")
        result = run_mega_cmd(["get", remote_path, dest_dir], timeout=1800)
        
        if result.returncode == 0:
            print("下载成功")
            break
        else:
            if attempt < max_retries - 1:
                print(f"下载失败，等待 2 秒后重试...")
                time.sleep(2)
            else:
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
    
    subparsers.add_parser("upload", help="上传源码压缩包到 MEGA")
    
    parser_download = subparsers.add_parser("download", help="从 MEGA 下载源码压缩包")
    parser_download.add_argument("remote_folder", help="MEGA 远程文件夹名")
    parser_download.add_argument("dest_dir", help="本地目标目录")
    
    subparsers.add_parser("delete", help="删除 MEGA 上的临时源码压缩包")
    
    args = parser.parse_args()
    
    if args.command == "upload":
        upload_to_mega()
    elif args.command == "download":
        download_from_mega(args)
    elif args.command == "delete":
        delete_from_mega()


if __name__ == "__main__":
    main()
