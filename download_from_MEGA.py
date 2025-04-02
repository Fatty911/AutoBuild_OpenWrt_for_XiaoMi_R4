#!/usr/bin/env python3
import sys
import subprocess
import shutil
import os

def check_megacmd_installed():
    if shutil.which("mega-login") is None:
        print("未检测到 MEGAcmd，正在尝试安装...")
        update = subprocess.run(["sudo", "apt-get", "update"], capture_output=True)
        if update.returncode != 0:
            print("更新软件包列表失败:", update.stderr.decode())
        
        install = subprocess.run(["sudo", "apt-get", "install", "-y", "megacmd"], capture_output=True)
        if install.returncode != 0:
            print("apt-get 安装失败，尝试动态下载并安装 MEGAcmd...")
            result = subprocess.run(["lsb_release", "-rs"], capture_output=True, text=True)
            if result.returncode != 0:
                print("获取 Ubuntu 版本失败:", result.stderr)
                sys.exit(1)
            ubuntu_version = result.stdout.strip()
            download_url = f"https://mega.nz/linux/repo/xUbuntu_{ubuntu_version}/amd64/megacmd-xUbuntu_{ubuntu_version}_amd64.deb"
            print(f"下载安装包: {download_url}")
            download = subprocess.run(["wget", download_url, "-O", "megacmd.deb"], capture_output=True)
            if download.returncode != 0:
                print("下载失败:", download.stderr.decode())
                sys.exit(1)
            
            install_deb = subprocess.run(["sudo", "dpkg", "-i", "megacmd.deb"], capture_output=True)
            if install_deb.returncode != 0:
                fix_deps = subprocess.run(["sudo", "apt-get", "install", "-f", "-y"], capture_output=True)
                if fix_deps.returncode != 0:
                    print("依赖修复失败:", fix_deps.stderr.decode())
                    sys.exit(1)
            
            os.remove("megacmd.deb")
            print("MEGAcmd 安装完成")
        
        # 验证安装
        version_check = subprocess.run(["mega-version"], capture_output=True, text=True)
        if version_check.returncode != 0:
            print("MEGAcmd 验证失败:", version_check.stderr)
            sys.exit(1)
        print("MEGAcmd 版本:", version_check.stdout.strip())
    else:
        print("MEGAcmd 已安装")

def mega_login(username, password):
    login = subprocess.run(["mega-login", username, password], capture_output=True, text=True)
    if login.returncode != 0:
        print("登录失败:", login.stderr)
        sys.exit(1)
    
    # 验证登录状态
    whoami = subprocess.run(["mega-whoami"], capture_output=True, text=True)
    if whoami.returncode != 0:
        print("登录状态检查失败:", whoami.stderr)
        sys.exit(1)
    print("当前登录用户:", whoami.stdout.strip())

def mega_download_folder(folder, dest_dir="."):
    # 创建目标目录
    os.makedirs(dest_dir, exist_ok=True)
    if not os.access(dest_dir, os.W_OK):
        print(f"错误: 目录 '{dest_dir}' 不可写")
        sys.exit(1)
    
    # 检查远程文件夹是否存在
    check_folder = subprocess.run(["mega-ls", f"mega:/{folder}"], capture_output=True, text=True)
    if check_folder.returncode != 0:
        print(f"错误: 远程文件夹 'mega:/{folder}' 不存在")
        print("详细输出:", check_folder.stderr)
        sys.exit(1)
    
    # 执行下载
    print(f"开始下载: mega:/{folder} -> {dest_dir}")
    download = subprocess.run(["mega-get", "-r", f"mega:/{folder}", dest_dir], capture_output=True, text=True)
    if download.returncode != 0:
        print("下载失败:", download.stderr)
        sys.exit(1)
    print("下载成功完成")

def main():
    if len(sys.argv) < 4 or len(sys.argv) > 5:
        print("用法: python3 download_from_mega.py <用户名> <密码> <远程文件夹> [本地目录]")
        sys.exit(1)
    
    check_megacmd_installed()
    username = sys.argv[1]
    password = sys.argv[2]
    folder = sys.argv[3]
    dest_dir = sys.argv[4] if len(sys.argv) == 5 else "."
    
    mega_login(username, password)
    mega_download_folder(folder, dest_dir)

if __name__ == "__main__":
    main()
