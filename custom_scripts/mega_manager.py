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


def run_mega_cmd(args, check=True, capture_output=True):
    """运行 MEGAcmd 命令"""
    cmd = ["mega-" + args[0]] + args[1:]
    print(f"执行: {' '.join(cmd)}")
    
    result = subprocess.run(
        cmd,
        capture_output=capture_output,
        text=True,
        check=False
    )
    
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


def upload_to_mega():
    """上传文件到 MEGA"""
    source = os.getenv("SOURCE")
    if not source:
        print("错误: 请设置 SOURCE 环境变量")
        sys.exit(1)
    
    ensure_logged_in()
    
    # 查找本地文件
    import glob
    tar_files = glob.glob(f"{source}.tar.gz")
    if not tar_files:
        print(f"错误: 未找到 {source}.tar.gz 文件")
        sys.exit(1)
    
    local_file = tar_files[0]
    remote_path = f"/{source}"
    
    # 创建远程文件夹（如果不存在）
    run_mega_cmd(["mkdir", "-p", remote_path], check=False)
    
    # 上传文件
    print(f"上传 {local_file} 到 {remote_path}/")
    result = run_mega_cmd(["put", "-c", local_file, remote_path + "/"])
    
    if result.returncode == 0:
        print("上传成功")
    else:
        print("上传失败")
        sys.exit(1)


def download_from_mega(args):
    """从 MEGA 下载文件"""
    remote_folder = args.remote_folder
    dest_dir = args.dest_dir
    
    ensure_logged_in()
    
    remote_path = f"/{remote_folder}"
    
    # 检查远程文件夹是否存在
    result = run_mega_cmd(["ls", remote_path], check=False)
    if result.returncode != 0:
        print(f"错误: 远程文件夹 {remote_path} 不存在")
        sys.exit(1)
    
    # 创建目标目录
    os.makedirs(dest_dir, exist_ok=True)
    
    # 下载文件
    print(f"从 {remote_path} 下载到 {dest_dir}")
    result = run_mega_cmd(["get", remote_path, dest_dir])
    
    if result.returncode == 0:
        print("下载成功")
    else:
        print("下载失败")
        sys.exit(1)


def delete_from_mega():
    """从 MEGA 删除文件"""
    source = os.getenv("SOURCE")
    if not source:
        print("错误: 请设置 SOURCE 环境变量")
        sys.exit(1)
    
    ensure_logged_in()
    
    remote_path = f"/{source}"
    
    # 检查文件夹是否存在
    result = run_mega_cmd(["ls", remote_path], check=False)
    if result.returncode != 0:
        print(f"文件夹 {remote_path} 不存在，无需删除")
        return
    
    # 删除文件夹
    print(f"删除 {remote_path}")
    result = run_mega_cmd(["rm", "-r", "-f", remote_path], check=False)
    
    if result.returncode == 0:
        print("删除成功")
    else:
        print(f"删除失败: {result.stderr}")


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
